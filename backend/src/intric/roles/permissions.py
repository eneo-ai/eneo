# MIT License

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from intric.main.exceptions import UnauthorizedException

if TYPE_CHECKING:
    from intric.users.user import UserInDB


class Permission(str, Enum):
    ASSISTANTS = "assistants"
    GROUP_CHATS = "group_chats"
    APPS = "apps"
    SERVICES = "services"
    COLLECTIONS = "collections"
    INSIGHTS = "insights"
    AI = "AI"
    EDITOR = "editor"
    ADMIN = "admin"
    WEBSITES = "websites"
    INTEGRATIONS = "integrations"
    FLOWS = "flows"
    FLOWS_VIEW = "flows_view"
    FLOWS_RUN = "flows_run"
    FLOWS_MANAGE = "flows_manage"
    FLOWS_AI_BUILDER = "flows_ai_builder"
    FLOWS_TRACE = "flows_trace"


_FLOW_PERMISSION_ALIASES: dict[Permission, tuple[Permission, ...]] = {
    Permission.FLOWS_VIEW: (
        Permission.FLOWS_VIEW,
        Permission.FLOWS_RUN,
        Permission.FLOWS_MANAGE,
        Permission.FLOWS,
    ),
    Permission.FLOWS_RUN: (
        Permission.FLOWS_RUN,
        Permission.FLOWS_MANAGE,
        Permission.FLOWS,
    ),
    Permission.FLOWS_MANAGE: (
        Permission.FLOWS_MANAGE,
        Permission.FLOWS,
    ),
    Permission.FLOWS_AI_BUILDER: (
        Permission.FLOWS_AI_BUILDER,
        Permission.FLOWS,
    ),
    Permission.FLOWS_TRACE: (
        Permission.FLOWS_TRACE,
        Permission.FLOWS,
    ),
}


def has_permission(
    permissions: list[Permission] | tuple[Permission, ...] | set[Permission],
    permission: Permission,
) -> bool:
    effective_permissions = _FLOW_PERMISSION_ALIASES.get(permission, (permission,))
    permission_set = set(permissions)
    return any(candidate in permission_set for candidate in effective_permissions)


def validate_permissions(permission: Permission):
    """This decorator can only be used on class methods
    where a user exists in the `self`.
    """

    def _validate(func):
        async def _inner(self, *args, **kwargs):
            if not has_permission(self.user.permissions, permission):
                raise UnauthorizedException(
                    f"Need permission {permission.value} in order to access"
                )

            return await func(self, *args, **kwargs)

        return _inner

    return _validate


def validate_permission(user: UserInDB, permission: Permission):
    if not has_permission(user.permissions, permission):
        raise UnauthorizedException(
            f"Need permission {permission.value} in order to access"
        )
