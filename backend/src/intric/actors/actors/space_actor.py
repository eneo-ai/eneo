from enum import Enum
from typing import TYPE_CHECKING, Union

from intric.main.models import ResourcePermission
from intric.modules.module import Modules
from intric.roles.permissions import Permission

if TYPE_CHECKING:
    from intric.apps.apps.app import App
    from intric.assistants.assistant import Assistant
    from intric.group_chat.domain.entities.group_chat import GroupChat
    from intric.spaces.space import Space
    from intric.users.user import UserInDB


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
            SpaceAction.READ, SpaceAction.CREATE, SpaceAction.EDIT, SpaceAction.DELETE,
            SpaceAction.PUBLISH, SpaceAction.INSIGHT_TOGGLE, SpaceAction.INSIGHT_VIEW,
        },
        SpaceResourceType.GROUP_CHAT: {
            SpaceAction.READ, SpaceAction.CREATE, SpaceAction.EDIT, SpaceAction.DELETE,
            SpaceAction.PUBLISH, SpaceAction.INSIGHT_TOGGLE, SpaceAction.INSIGHT_VIEW,
        },
        SpaceResourceType.APP: {
            SpaceAction.READ, SpaceAction.CREATE, SpaceAction.EDIT, SpaceAction.DELETE, SpaceAction.PUBLISH,
        },
        SpaceResourceType.SERVICE: {
            SpaceAction.READ, SpaceAction.CREATE, SpaceAction.EDIT, SpaceAction.DELETE, SpaceAction.PUBLISH,
        },
        SpaceResourceType.COLLECTION: {
            SpaceAction.READ, SpaceAction.CREATE, SpaceAction.EDIT, SpaceAction.DELETE,
        },
        SpaceResourceType.WEBSITE: {
            SpaceAction.READ, SpaceAction.CREATE, SpaceAction.EDIT, SpaceAction.DELETE,
        },
        SpaceResourceType.INTEGRATION_KNOWLEDGE: {
            SpaceAction.READ, SpaceAction.CREATE, SpaceAction.EDIT, SpaceAction.DELETE,
        },
        SpaceResourceType.INFO_BLOB: {
            SpaceAction.READ, SpaceAction.CREATE, SpaceAction.DELETE,
        },
        SpaceResourceType.SPACE: {
            SpaceAction.READ, SpaceAction.EDIT, SpaceAction.DELETE,
        },
        SpaceResourceType.MEMBER: {
            SpaceAction.READ, SpaceAction.CREATE, SpaceAction.EDIT, SpaceAction.DELETE,
        },
        # Chat / default-assistenten synlig & redigerbar endast för admin:
        SpaceResourceType.DEFAULT_ASSISTANT: {
            SpaceAction.READ, SpaceAction.EDIT,
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
            SpaceResourceType.INTEGRATION_KNOWLEDGE: Permission.INTEGRATION_KNOWLEDGE_LIST,
        }

        return permission_map.get(resource_type)

    def _get_role(self):
        space_member = self.space.members.get(self.user.id)

        if self.space.is_personal():
            if self.user.id == self.space.user_id:
                return SpaceRole.OWNER

        return space_member.role if space_member else None

    def _get_permissions(self, role: SpaceRole):
        if self.space.is_personal():
            return self._personal_space_permissions.get(role, {})
        if self.space.is_organization(): 
            return self._org_space_permissions.get(role, {})
        return self._shared_space_permissions.get(role, {})
    
    def can_perform_action(
        self,
        action: SpaceAction,
        resource_type: SpaceResourceType,
        resource: Union["Assistant", "GroupChat", "App"] = None,
    ):
        role = self._get_role()
        permissions = self._get_permissions(role=role)

        if (
            self.space.is_personal()
            and resource_type in PERMISSION_RESOURCES
        ):
            permission = self._to_permisson(resource_type=resource_type)
            has_permission = permission in self.user.permissions if permission else False
            if not has_permission and not (
                resource_type == SpaceResourceType.WEBSITE and action == SpaceAction.READ
            ):
                return False

        if (
            resource_type == SpaceResourceType.SERVICE
            and Modules.INTRIC_APPLICATIONS not in self.user.modules
        ):
            return False

        if role == SpaceRole.VIEWER and resource_type in PUBLISHABLE_RESOURCES:
            if resource is not None and not resource.published:
                return False

        if resource_type in INSIGHT_RESOURCES and action == SpaceAction.INSIGHT_VIEW:
            if resource is not None and not resource.insight_enabled:
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

    def can_read_integration_knowledge_list(self):
        return self.can_perform_action(
            action=SpaceAction.READ,
            resource_type=SpaceResourceType.INTEGRATION_KNOWLEDGE,
        )

    def can_create_integration_knowledge_list(self):
        return self.can_perform_action(
            action=SpaceAction.CREATE,
            resource_type=SpaceResourceType.INTEGRATION_KNOWLEDGE,
        )

    def can_delete_integration_knowledge_list(self):
        return self.can_perform_action(
            action=SpaceAction.DELETE,
            resource_type=SpaceResourceType.INTEGRATION_KNOWLEDGE,
        )

    def can_edit_integration_knowledge_list(self):
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
    ):
        permissions = []

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

    def get_assistant_permissions(self, assistant: "Assistant"):
        permissions = []

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

    def get_group_chat_permissions(self, group_chat: "GroupChat"):
        return self._get_resource_permissions(
            can_edit=self.can_edit_group_chats(),
            can_delete=self.can_delete_group_chats(),
            can_publish=self.can_publish_group_chats(),
            can_access_insight=self.can_access_insight_group_chat(group_chat=group_chat),
            can_toggle_insight=self.can_toggle_insight(),
        )

    def get_app_permissions(self):
        return self._get_resource_permissions(
            can_edit=self.can_edit_apps(),
            can_delete=self.can_delete_apps(),
            can_publish=self.can_publish_apps(),
            can_access_insight=False,
            can_toggle_insight=False,
        )

    def get_collection_permissions(self):
        return self._get_resource_permissions(
            can_edit=self.can_edit_collections(),
            can_delete=self.can_delete_collections(),
            can_publish=False,
            can_access_insight=False,
            can_toggle_insight=False,
        )

    def get_website_permissions(self):
        return self._get_resource_permissions(
            can_edit=self.can_edit_websites(),
            can_delete=self.can_delete_websites(),
            can_publish=False,
            can_access_insight=False,
            can_toggle_insight=False,
        )

    def get_integration_knowledge_list_permissions(self):
        return self._get_resource_permissions(
            can_edit=self.can_edit_integration_knowledge_list(),
            can_delete=self.can_delete_integration_knowledge_list(),
            can_publish=False,
            can_access_insight=False,
            can_toggle_insight=False,
        )

    def get_service_permissions(self):
        return self._get_resource_permissions(
            can_edit=self.can_edit_services(),
            can_delete=self.can_delete_services(),
            can_publish=False,
            can_access_insight=False,
            can_toggle_insight=False,
        )

    def get_available_roles(self):
        if self.space.is_personal():
            return []

        roles = [SpaceRole.ADMIN, SpaceRole.EDITOR, SpaceRole.VIEWER]

        return roles
