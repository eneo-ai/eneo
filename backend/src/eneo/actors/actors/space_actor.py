from enum import Enum
from typing import TYPE_CHECKING, Optional, Union

from eneo.authentication.auth_models import is_service_api_key
from eneo.main.models import ResourcePermission
from eneo.modules.module import Modules
from eneo.roles.permissions import Permission

if TYPE_CHECKING:
    from eneo.apps.apps.app import App
    from eneo.assistants.assistant import Assistant
    from eneo.group_chat.domain.entities.group_chat import GroupChat
    from eneo.spaces.space import Space
    from eneo.users.user import UserInDB


class SpaceAction(str, Enum):
    READ = "read"
    CREATE = "create"
    EDIT = "edit"
    DELETE = "delete"
    PUBLISH = "publish"
    INSIGHT_VIEW = "insight_view"
    INSIGHT_TOGGLE = "insight_toggle"


class SpaceResourceType(str, Enum):
    ASSISTANT = "assistant"
    GROUP_CHAT = "group_chat"
    APP = "app"
    SERVICE = "service"
    COLLECTION = "collection"
    WEBSITE = "website"
    INTEGRATION_KNOWLEDGE = "integration_knowledge"
    INFO_BLOB = "info blob"
    SPACE = "space"
    MEMBER = "member"
    GROUP_MEMBER = "group_member"
    DEFAULT_ASSISTANT = "default assistant"


class SpaceRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


SHARED_SPACE_PERMISSIONS = {
    SpaceRole.VIEWER: {
        SpaceResourceType.ASSISTANT: {SpaceAction.READ},
        SpaceResourceType.GROUP_CHAT: {SpaceAction.READ},
        SpaceResourceType.APP: {SpaceAction.READ},
        # Only published resources are readable -- enforced in code
        SpaceResourceType.INFO_BLOB: {SpaceAction.READ},
        SpaceResourceType.SPACE: {
            SpaceAction.READ,
        },
        SpaceResourceType.DEFAULT_ASSISTANT: {
            SpaceAction.READ,
        },
        SpaceResourceType.INTEGRATION_KNOWLEDGE: {
            SpaceAction.READ,
        },
    },
    SpaceRole.EDITOR: {
        SpaceResourceType.ASSISTANT: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
            SpaceAction.PUBLISH,
            SpaceAction.INSIGHT_VIEW,
        },
        SpaceResourceType.GROUP_CHAT: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
            SpaceAction.PUBLISH,
            SpaceAction.INSIGHT_VIEW,
        },
        SpaceResourceType.APP: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
            SpaceAction.PUBLISH,
        },
        SpaceResourceType.SERVICE: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
            SpaceAction.PUBLISH,
        },
        SpaceResourceType.COLLECTION: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
            # Note: No publish
        },
        SpaceResourceType.WEBSITE: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
            # Note: No publish
        },
        SpaceResourceType.INTEGRATION_KNOWLEDGE: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
            # Note: No publish
        },
        SpaceResourceType.INFO_BLOB: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.DELETE,
        },
        SpaceResourceType.SPACE: {
            SpaceAction.READ,
        },
        SpaceResourceType.DEFAULT_ASSISTANT: {
            SpaceAction.READ,
        },
    },
    SpaceRole.ADMIN: {
        SpaceResourceType.ASSISTANT: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
            SpaceAction.PUBLISH,
            SpaceAction.INSIGHT_TOGGLE,
            SpaceAction.INSIGHT_VIEW,
        },
        SpaceResourceType.GROUP_CHAT: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
            SpaceAction.PUBLISH,
            SpaceAction.INSIGHT_TOGGLE,
            SpaceAction.INSIGHT_VIEW,
        },
        SpaceResourceType.APP: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
            SpaceAction.PUBLISH,
        },
        SpaceResourceType.SERVICE: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
            SpaceAction.PUBLISH,
        },
        SpaceResourceType.COLLECTION: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
            # Note: No publish
        },
        SpaceResourceType.WEBSITE: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
            # Note: No publish
        },
        SpaceResourceType.INTEGRATION_KNOWLEDGE: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
            # Note: No publish
        },
        SpaceResourceType.INFO_BLOB: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.DELETE,
        },
        SpaceResourceType.SPACE: {
            SpaceAction.READ,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
        },
        SpaceResourceType.MEMBER: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
        },
        SpaceResourceType.GROUP_MEMBER: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
        },
        SpaceResourceType.DEFAULT_ASSISTANT: {
            SpaceAction.READ,
            SpaceAction.EDIT,
        },
    },
}

PERSONAL_SPACE_PERMISSIONS = {
    SpaceRole.OWNER: {
        SpaceResourceType.ASSISTANT: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
            # Note: No publish
        },
        SpaceResourceType.GROUP_CHAT: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
            # Note: No publish
        },
        SpaceResourceType.APP: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
            # Note: No publish
        },
        SpaceResourceType.SERVICE: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
            # Note: No publish
        },
        SpaceResourceType.COLLECTION: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
            # Note: No publish
        },
        SpaceResourceType.WEBSITE: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
            # Note: No publish
        },
        SpaceResourceType.INTEGRATION_KNOWLEDGE: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
            # Note: No publish
        },
        SpaceResourceType.INFO_BLOB: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.DELETE,
        },
        SpaceResourceType.SPACE: {
            SpaceAction.READ,
        },
        SpaceResourceType.DEFAULT_ASSISTANT: {
            SpaceAction.READ,
            SpaceAction.EDIT,
        },
    },
}

ORG_SPACE_PERMISSIONS = {
    SpaceRole.VIEWER: {
        # Ingen läsrätt alls i org-space
    },
    SpaceRole.EDITOR: {
        # Ingen läsrätt alls i org-space
    },
    SpaceRole.ADMIN: {
        SpaceResourceType.ASSISTANT: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
            SpaceAction.PUBLISH,
            SpaceAction.INSIGHT_TOGGLE,
            SpaceAction.INSIGHT_VIEW,
        },
        SpaceResourceType.GROUP_CHAT: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
            SpaceAction.PUBLISH,
            SpaceAction.INSIGHT_TOGGLE,
            SpaceAction.INSIGHT_VIEW,
        },
        SpaceResourceType.APP: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
            SpaceAction.PUBLISH,
        },
        SpaceResourceType.SERVICE: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
            SpaceAction.PUBLISH,
        },
        SpaceResourceType.COLLECTION: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
        },
        SpaceResourceType.WEBSITE: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
        },
        SpaceResourceType.INTEGRATION_KNOWLEDGE: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
        },
        SpaceResourceType.INFO_BLOB: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.DELETE,
        },
        SpaceResourceType.SPACE: {
            SpaceAction.READ,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
        },
        SpaceResourceType.MEMBER: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
        },
        SpaceResourceType.GROUP_MEMBER: {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.DELETE,
        },
        # Chat / default-assistenten synlig & redigerbar endast för admin:
        SpaceResourceType.DEFAULT_ASSISTANT: {
            SpaceAction.READ,
            SpaceAction.EDIT,
        },
    },
}

PROPRIETARY_RESOURCES = {}
PERMISSION_RESOURCES = {
    SpaceResourceType.ASSISTANT,
    SpaceResourceType.GROUP_CHAT,
    SpaceResourceType.APP,
    SpaceResourceType.SERVICE,
    SpaceResourceType.COLLECTION,
    SpaceResourceType.WEBSITE,
    SpaceResourceType.INTEGRATION_KNOWLEDGE,
}
PUBLISHABLE_RESOURCES = {
    SpaceResourceType.ASSISTANT,
    SpaceResourceType.GROUP_CHAT,
    SpaceResourceType.APP,
}
INSIGHT_RESOURCES = {
    SpaceResourceType.ASSISTANT,
    SpaceResourceType.GROUP_CHAT,
}
AccessControlList = dict[SpaceRole, dict[SpaceResourceType, set[SpaceAction]]]


# TODO: Let the services use can_perform_action()
class SpaceActor:
    def __init__(
        self,
        user: "UserInDB",
        space: "Space",
        shared_space_permissions: AccessControlList = SHARED_SPACE_PERMISSIONS,
        personal_space_permissions: AccessControlList = PERSONAL_SPACE_PERMISSIONS,
        org_space_permissions: AccessControlList = ORG_SPACE_PERMISSIONS,
    ):
        super().__init__()
        self.user = user
        self.space = space
        self._shared_space_permissions = shared_space_permissions
        self._personal_space_permissions = personal_space_permissions
        self._org_space_permissions = org_space_permissions

    def _to_permisson(self, resource_type: SpaceResourceType):
        permission_map = {
            SpaceResourceType.ASSISTANT: Permission.ASSISTANTS,
            SpaceResourceType.GROUP_CHAT: Permission.GROUP_CHATS,
            SpaceResourceType.APP: Permission.APPS,
            SpaceResourceType.SERVICE: Permission.SERVICES,
            SpaceResourceType.COLLECTION: Permission.COLLECTIONS,
            SpaceResourceType.WEBSITE: Permission.WEBSITES,
            SpaceResourceType.INTEGRATION_KNOWLEDGE: Permission.INTEGRATIONS,
        }

        return permission_map.get(resource_type)

    def _get_role(self):
        # Service keys have no user membership — the key is the only access
        # path into any space.
        if self._is_service_api_key():
            return self._get_api_key_role()

        # User-owned API key whose scope does not cover this space: deny.
        # The credential used to authenticate this request does not extend
        # to this space, so the user's membership here is irrelevant.
        key = getattr(self.user, "active_api_key", None)
        if key is not None and self._get_api_key_role() is None:
            return None

        # Personal space → OWNER for the owning user.
        if self.space.is_personal():
            if self.user.id == self.space.user_id:
                return SpaceRole.OWNER
            return None

        direct_role = self._get_direct_role()
        group_role = self._get_highest_group_role()
        return self._get_highest_role(direct_role, group_role)

    def _is_service_api_key(self) -> bool:
        return is_service_api_key(self.user)

    def _get_api_key_role(self) -> SpaceRole | None:
        """Derive a space role from the active API key's scope and permission.

        Applies to both service and user-owned keys. Returns None when no
        key is active, or when the key's scope does not cover this space.

        Scope → access:
          - tenant-scoped     → every space in the tenant
          - space-scoped      → only the matching space
          - assistant/app     → only the parent space of that resource

        Permission → role:
          - read  → VIEWER
          - write → EDITOR
          - admin → ADMIN
        """
        key = getattr(self.user, "active_api_key", None)
        if key is None:
            return None

        scope_type = key.scope_type
        if hasattr(scope_type, "value"):
            scope_type = scope_type.value

        if scope_type == "tenant":
            pass  # tenant keys cover every space
        elif scope_type == "space":
            if key.scope_id != self.space.id:
                return None
        elif scope_type in ("assistant", "app"):
            resource_ids: set[object] = set()
            if scope_type == "assistant":
                resource_ids = {a.id for a in (self.space.assistants or [])}
            elif scope_type == "app":
                resource_ids = {a.id for a in (self.space.apps or [])}
            if key.scope_id not in resource_ids:
                return None
        else:
            return None

        permission = key.permission
        if hasattr(permission, "value"):
            permission = permission.value

        _PERMISSION_TO_ROLE = {
            "read": SpaceRole.VIEWER,
            "write": SpaceRole.EDITOR,
            "admin": SpaceRole.ADMIN,
        }
        return _PERMISSION_TO_ROLE.get(permission)

    def _get_direct_role(self) -> SpaceRole | None:
        """Get the user's role from direct membership."""
        space_member = self.space.members.get(self.user.id)
        return SpaceRole(space_member.role) if space_member else None

    def _get_highest_group_role(self) -> SpaceRole | None:
        """Find the highest role the user has through group membership."""
        user_group_ids = self.user.user_groups_ids
        if not user_group_ids:
            return None

        highest = None
        for group_member in self.space.group_members.values():
            if group_member.id in user_group_ids:
                group_role = SpaceRole(group_member.role)
                highest = self._get_highest_role(highest, group_role)

        return highest

    _ROLE_PRIORITY = {
        SpaceRole.OWNER: 4,
        SpaceRole.ADMIN: 3,
        SpaceRole.EDITOR: 2,
        SpaceRole.VIEWER: 1,
    }

    # Actions a user-owned API key is allowed to exercise, per key permission
    # level. Aligned with the HTTP method→permission map: ``read`` covers
    # GET-equivalent actions, ``write`` covers POST/PUT/PATCH-equivalent, and
    # ``admin`` lifts the constraint entirely (DELETE included). Applied on
    # top of the user's role so the effective permissions are the intersection.
    _KEY_PERMISSION_ACTIONS: dict[str, set[SpaceAction]] = {
        "read": {SpaceAction.READ, SpaceAction.INSIGHT_VIEW},
        "write": {
            SpaceAction.READ,
            SpaceAction.CREATE,
            SpaceAction.EDIT,
            SpaceAction.PUBLISH,
            SpaceAction.INSIGHT_VIEW,
            SpaceAction.INSIGHT_TOGGLE,
        },
    }

    def _get_highest_role(
        self, role1: SpaceRole | None, role2: SpaceRole | None
    ) -> SpaceRole | None:
        """Return the highest privilege role between two roles.

        Role hierarchy (highest to lowest): OWNER > ADMIN > EDITOR > VIEWER
        """
        if role1 is None:
            return role2
        if role2 is None:
            return role1

        return (
            role1
            if self._ROLE_PRIORITY.get(role1, 0) >= self._ROLE_PRIORITY.get(role2, 0)
            else role2
        )

    def _get_api_key_action_constraint(self) -> set[SpaceAction] | None:
        """Return the action set a user-owned API key permits, or None for
        no constraint (service key, admin key, or no active key)."""
        key = getattr(self.user, "active_api_key", None)
        if key is None:
            return None
        if self._is_service_api_key():
            return None

        permission = key.permission
        if hasattr(permission, "value"):
            permission = permission.value
        if permission == "admin":
            return None
        return self._KEY_PERMISSION_ACTIONS.get(permission, set())

    def _get_permissions(
        self, role: SpaceRole | None
    ) -> dict[SpaceResourceType, set[SpaceAction]]:
        if role is None:
            return {}
        if self.space.is_personal():
            base = self._personal_space_permissions.get(role, {})
        elif self.space.is_organization():
            base = self._org_space_permissions.get(role, {})
        else:
            base = self._shared_space_permissions.get(role, {})

        allowed = self._get_api_key_action_constraint()
        if allowed is None:
            return base
        return {resource: actions & allowed for resource, actions in base.items()}

    def can_perform_action(
        self,
        action: SpaceAction,
        resource_type: SpaceResourceType,
        resource: Optional[Union["Assistant", "GroupChat", "App"]] = None,
    ):
        role = self._get_role()
        permissions = self._get_permissions(role=role)

        # Check tenant-level permissions for all spaces (personal and shared).
        # Service API keys authorize via scope+permission, not user roles —
        # their synthetic user has no roles, so skip this gate for them.
        if resource_type in PERMISSION_RESOURCES and not self._is_service_api_key():
            permission = self._to_permisson(resource_type=resource_type)
            has_permission = (
                permission in self.user.permissions if permission else False
            )
            if not has_permission and not (
                resource_type
                in {SpaceResourceType.WEBSITE, SpaceResourceType.INTEGRATION_KNOWLEDGE}
                and action == SpaceAction.READ
            ):
                return False

        # The personal chat (personal space default assistant) is gated by its
        # own tenant permission, decoupled from ASSISTANTS so a baseline role can
        # grant chat without management of assistants. Service keys authorize via
        # scope, not user roles, so they bypass this gate (as above).
        if (
            resource_type == SpaceResourceType.DEFAULT_ASSISTANT
            and self.space.is_personal()
            and not self._is_service_api_key()
            and Permission.PERSONAL_CHAT not in self.user.permissions
        ):
            return False

        if (
            resource_type == SpaceResourceType.SERVICE
            and Modules.ENEO_APPLICATIONS not in self.user.modules
        ):
            return False

        if role == SpaceRole.VIEWER and resource_type in PUBLISHABLE_RESOURCES:
            if resource is not None and not resource.published:
                return False

        if resource_type in INSIGHT_RESOURCES and action == SpaceAction.INSIGHT_VIEW:
            if resource is not None and not resource.insight_enabled:  # type: ignore[attr-defined]
                return False

        allowed_actions = permissions.get(resource_type, set())
        return action in allowed_actions

    def can_read_space(self):
        return self.can_perform_action(
            action=SpaceAction.READ,
            resource_type=SpaceResourceType.SPACE,
        )

    def can_edit_space(self):
        return self.can_perform_action(
            action=SpaceAction.EDIT,
            resource_type=SpaceResourceType.SPACE,
        )

    def can_delete_space(self):
        return self.can_perform_action(
            action=SpaceAction.DELETE,
            resource_type=SpaceResourceType.SPACE,
        )

    def can_read_members(self):
        return self.can_perform_action(
            action=SpaceAction.READ,
            resource_type=SpaceResourceType.MEMBER,
        )

    def can_read_group_members(self):
        return self.can_perform_action(
            action=SpaceAction.READ,
            resource_type=SpaceResourceType.GROUP_MEMBER,
        )

    def can_add_group_members(self):
        return self.can_perform_action(
            action=SpaceAction.CREATE,
            resource_type=SpaceResourceType.GROUP_MEMBER,
        )

    def can_edit_group_members(self):
        return self.can_perform_action(
            action=SpaceAction.EDIT,
            resource_type=SpaceResourceType.GROUP_MEMBER,
        )

    def can_delete_group_members(self):
        return self.can_perform_action(
            action=SpaceAction.DELETE,
            resource_type=SpaceResourceType.GROUP_MEMBER,
        )

    def can_read_default_assistant(self):
        return self.can_perform_action(
            action=SpaceAction.READ,
            resource_type=SpaceResourceType.DEFAULT_ASSISTANT,
        )

    def can_edit_default_assistant(self):
        return self.can_perform_action(
            action=SpaceAction.EDIT,
            resource_type=SpaceResourceType.DEFAULT_ASSISTANT,
        )

    def can_read_assistants(self):
        return self.can_perform_action(
            action=SpaceAction.READ,
            resource_type=SpaceResourceType.ASSISTANT,
        )

    def can_create_assistants(self):
        return self.can_perform_action(
            action=SpaceAction.CREATE,
            resource_type=SpaceResourceType.ASSISTANT,
        )

    def can_read_assistant(self, assistant: "Assistant"):
        return self.can_perform_action(
            action=SpaceAction.READ,
            resource_type=SpaceResourceType.ASSISTANT,
            resource=assistant,
        )

    def can_edit_assistants(self):
        return self.can_perform_action(
            action=SpaceAction.EDIT,
            resource_type=SpaceResourceType.ASSISTANT,
        )

    def can_delete_assistants(self):
        return self.can_perform_action(
            action=SpaceAction.DELETE,
            resource_type=SpaceResourceType.ASSISTANT,
        )

    def can_read_prompts_of_assistants(self):
        # Considered editing an Assistant.
        # We might consider adding a separate permission
        # for this.
        return self.can_perform_action(
            action=SpaceAction.EDIT,
            resource_type=SpaceResourceType.ASSISTANT,
        )

    def can_publish_assistants(self):
        return self.can_perform_action(
            action=SpaceAction.PUBLISH,
            resource_type=SpaceResourceType.ASSISTANT,
        )

    def can_create_group_chats(self):
        return self.can_perform_action(
            action=SpaceAction.CREATE,
            resource_type=SpaceResourceType.GROUP_CHAT,
        )

    def can_edit_group_chats(self):
        return self.can_perform_action(
            action=SpaceAction.EDIT,
            resource_type=SpaceResourceType.GROUP_CHAT,
        )

    def can_delete_group_chats(self):
        return self.can_perform_action(
            action=SpaceAction.DELETE,
            resource_type=SpaceResourceType.GROUP_CHAT,
        )

    def can_read_group_chats(self):
        return self.can_perform_action(
            action=SpaceAction.READ,
            resource_type=SpaceResourceType.GROUP_CHAT,
        )

    def can_read_group_chat(self, group_chat: "GroupChat"):
        return self.can_perform_action(
            action=SpaceAction.READ,
            resource_type=SpaceResourceType.GROUP_CHAT,
            resource=group_chat,
        )

    def can_publish_group_chats(self):
        return self.can_perform_action(
            action=SpaceAction.PUBLISH,
            resource_type=SpaceResourceType.GROUP_CHAT,
        )

    # TODO: can_read?

    def can_read_apps(self):
        return self.can_perform_action(
            action=SpaceAction.READ,
            resource_type=SpaceResourceType.APP,
        )

    def can_create_apps(self):
        return self.can_perform_action(
            action=SpaceAction.CREATE,
            resource_type=SpaceResourceType.APP,
        )

    def can_read_app(self, app: "App"):
        return self.can_perform_action(
            action=SpaceAction.READ,
            resource_type=SpaceResourceType.APP,
            resource=app,
        )

    def can_edit_apps(self):
        return self.can_perform_action(
            action=SpaceAction.EDIT,
            resource_type=SpaceResourceType.APP,
        )

    def can_delete_apps(self):
        return self.can_perform_action(
            action=SpaceAction.DELETE,
            resource_type=SpaceResourceType.APP,
        )

    def can_read_prompts_of_apps(self):
        # Considered editing an App.
        # We might consider adding a separate permission
        # for this.
        return self.can_perform_action(
            action=SpaceAction.EDIT,
            resource_type=SpaceResourceType.APP,
        )

    def can_publish_apps(self):
        return self.can_perform_action(
            action=SpaceAction.PUBLISH,
            resource_type=SpaceResourceType.APP,
        )

    def can_toggle_insight(self):
        # NOTE: if user can toggle insight on assistants => true for group chats as well
        return self.can_perform_action(
            action=SpaceAction.INSIGHT_TOGGLE,
            resource_type=SpaceResourceType.ASSISTANT,
        )

    def can_access_insight_group_chat(self, group_chat: "GroupChat"):
        return self.can_perform_action(
            action=SpaceAction.INSIGHT_VIEW,
            resource_type=SpaceResourceType.GROUP_CHAT,
            resource=group_chat,
        )

    def can_access_insight_assistant(self, assistant: "Assistant"):
        return self.can_perform_action(
            action=SpaceAction.INSIGHT_VIEW,
            resource_type=SpaceResourceType.ASSISTANT,
            resource=assistant,
        )

    def can_read_collections(self):
        return self.can_perform_action(
            action=SpaceAction.READ,
            resource_type=SpaceResourceType.COLLECTION,
        )

    def can_create_collections(self):
        return self.can_perform_action(
            action=SpaceAction.CREATE,
            resource_type=SpaceResourceType.COLLECTION,
        )

    def can_edit_collections(self):
        return self.can_perform_action(
            action=SpaceAction.EDIT,
            resource_type=SpaceResourceType.COLLECTION,
        )

    def can_delete_collections(self):
        return self.can_perform_action(
            action=SpaceAction.DELETE,
            resource_type=SpaceResourceType.COLLECTION,
        )

    def can_read_websites(self):
        return self.can_perform_action(
            action=SpaceAction.READ,
            resource_type=SpaceResourceType.WEBSITE,
        )

    def can_create_websites(self):
        return self.can_perform_action(
            action=SpaceAction.CREATE,
            resource_type=SpaceResourceType.WEBSITE,
        )

    def can_edit_websites(self):
        return self.can_perform_action(
            action=SpaceAction.EDIT,
            resource_type=SpaceResourceType.WEBSITE,
        )

    def can_delete_websites(self):
        return self.can_perform_action(
            action=SpaceAction.DELETE,
            resource_type=SpaceResourceType.WEBSITE,
        )

    def can_read_integrations(self):
        return self.can_perform_action(
            action=SpaceAction.READ,
            resource_type=SpaceResourceType.INTEGRATION_KNOWLEDGE,
        )

    def can_create_integrations(self):
        return self.can_perform_action(
            action=SpaceAction.CREATE,
            resource_type=SpaceResourceType.INTEGRATION_KNOWLEDGE,
        )

    def can_delete_integrations(self):
        return self.can_perform_action(
            action=SpaceAction.DELETE,
            resource_type=SpaceResourceType.INTEGRATION_KNOWLEDGE,
        )

    def can_edit_integrations(self):
        return self.can_perform_action(
            action=SpaceAction.EDIT,
            resource_type=SpaceResourceType.INTEGRATION_KNOWLEDGE,
        )

    def can_read_info_blobs(self):
        return self.can_perform_action(
            action=SpaceAction.READ,
            resource_type=SpaceResourceType.INFO_BLOB,
        )

    def can_create_info_blobs(self):
        return self.can_perform_action(
            action=SpaceAction.CREATE,
            resource_type=SpaceResourceType.INFO_BLOB,
        )

    def can_delete_info_blobs(self):
        return self.can_perform_action(
            action=SpaceAction.DELETE,
            resource_type=SpaceResourceType.INFO_BLOB,
        )

    def can_read_services(self):
        return self.can_perform_action(
            action=SpaceAction.READ,
            resource_type=SpaceResourceType.SERVICE,
        )

    def can_create_services(self):
        return self.can_perform_action(
            action=SpaceAction.CREATE,
            resource_type=SpaceResourceType.SERVICE,
        )

    def can_edit_services(self):
        return self.can_perform_action(
            action=SpaceAction.EDIT,
            resource_type=SpaceResourceType.SERVICE,
        )

    def can_delete_services(self):
        return self.can_perform_action(
            action=SpaceAction.DELETE,
            resource_type=SpaceResourceType.SERVICE,
        )

    def _get_resource_permissions(
        self,
        can_edit: bool,
        can_delete: bool,
        can_publish: bool,
        can_access_insight: bool,
        can_toggle_insight: bool,
    ) -> list[ResourcePermission]:
        permissions: list[ResourcePermission] = []

        if can_edit:
            permissions.append(ResourcePermission.EDIT)

        if can_delete:
            permissions.append(ResourcePermission.DELETE)

        if can_publish:
            permissions.append(ResourcePermission.PUBLISH)

        if can_access_insight:
            permissions.append(ResourcePermission.INSIGHT_VIEW)

        if can_toggle_insight:
            permissions.append(ResourcePermission.INSIGHT_TOGGLE)

        return permissions

    def get_assistant_permissions(
        self, assistant: "Assistant"
    ) -> list[ResourcePermission]:
        permissions: list[ResourcePermission] = []

        # TODO: Getting permissions should be revisited after
        # Space is the aggregate root
        if (
            self.space.default_assistant is not None
            and assistant.id == self.space.default_assistant.id
        ):
            if self.can_read_default_assistant():
                permissions.append(ResourcePermission.READ)

            if self.can_edit_default_assistant():
                permissions.append(ResourcePermission.EDIT)

            return permissions

        return self._get_resource_permissions(
            can_edit=self.can_edit_assistants(),
            can_delete=self.can_delete_assistants(),
            can_publish=self.can_publish_assistants(),
            can_access_insight=self.can_access_insight_assistant(assistant=assistant),
            can_toggle_insight=self.can_toggle_insight(),
        )

    def get_group_chat_permissions(
        self, group_chat: "GroupChat"
    ) -> list[ResourcePermission]:
        return self._get_resource_permissions(
            can_edit=self.can_edit_group_chats(),
            can_delete=self.can_delete_group_chats(),
            can_publish=self.can_publish_group_chats(),
            can_access_insight=self.can_access_insight_group_chat(
                group_chat=group_chat
            ),
            can_toggle_insight=self.can_toggle_insight(),
        )

    def get_app_permissions(self) -> list[ResourcePermission]:
        return self._get_resource_permissions(
            can_edit=self.can_edit_apps(),
            can_delete=self.can_delete_apps(),
            can_publish=self.can_publish_apps(),
            can_access_insight=False,
            can_toggle_insight=False,
        )

    def get_collection_permissions(self) -> list[ResourcePermission]:
        return self._get_resource_permissions(
            can_edit=self.can_edit_collections(),
            can_delete=self.can_delete_collections(),
            can_publish=False,
            can_access_insight=False,
            can_toggle_insight=False,
        )

    def get_website_permissions(self) -> list[ResourcePermission]:
        return self._get_resource_permissions(
            can_edit=self.can_edit_websites(),
            can_delete=self.can_delete_websites(),
            can_publish=False,
            can_access_insight=False,
            can_toggle_insight=False,
        )

    def get_integrations_permissions(self) -> list[ResourcePermission]:
        return self._get_resource_permissions(
            can_edit=self.can_edit_integrations(),
            can_delete=self.can_delete_integrations(),
            can_publish=False,
            can_access_insight=False,
            can_toggle_insight=False,
        )

    def get_service_permissions(self) -> list[ResourcePermission]:
        return self._get_resource_permissions(
            can_edit=self.can_edit_services(),
            can_delete=self.can_delete_services(),
            can_publish=False,
            can_access_insight=False,
            can_toggle_insight=False,
        )

    def get_available_roles(self) -> list[SpaceRole]:
        if self.space.is_personal():
            return []

        return [SpaceRole.ADMIN, SpaceRole.EDITOR, SpaceRole.VIEWER]
