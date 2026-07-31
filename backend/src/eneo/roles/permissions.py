from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Coroutine, TypeVar

from eneo.main.exceptions import UnauthorizedException

if TYPE_CHECKING:
    from eneo.users.user import UserInDB

_F = TypeVar("_F", bound=Callable[..., Coroutine[Any, Any, Any]])


class Permission(str, Enum):
    ASSISTANTS = "assistants"
    SKILLS = "skills"
    SKILLS_MANAGEMENT = "skills_management"
    PERSONAL_CHAT = "personal_chat"
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
    SHARED_SPACES = "shared_spaces"
    API_KEYS = "api_keys"
    FLOWS = "flows"
    FLOWS_VIEW = "flows_view"
    FLOWS_RUN = "flows_run"
    FLOWS_MANAGE = "flows_manage"
    FLOWS_AI_BUILDER = "flows_ai_builder"
    FLOWS_TRACE = "flows_trace"
    ASSISTANT_DEBUG = "assistant_debug"


_FLOW_PERMISSION_ALIASES: dict[Permission, tuple[Permission, ...]] = {
    # Existing tenants may still carry the pre-granular `flows` grant in role
    # rows. Keep the compatibility rule centralized here so routers and
    # services can require the explicit permission they actually need.
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


def validate_permissions(permission: Permission) -> Callable[[_F], _F]:
    """This decorator can only be used on class methods
    where a user exists in the `self`.
    """

    def _validate(func: _F) -> _F:
        async def _inner(self: Any, *args: Any, **kwargs: Any) -> Any:
            if not has_permission(self.user.permissions, permission):
                raise UnauthorizedException(
                    f"Need permission {permission.value} in order to access"
                )

            return await func(self, *args, **kwargs)

        return _inner  # type: ignore[return-value]  # TypeVar bound wrapping

    return _validate  # type: ignore[return-value]  # TypeVar bound wrapping


def validate_permission(user: UserInDB, permission: Permission):
    if not has_permission(user.permissions, permission):
        raise UnauthorizedException(
            f"Need permission {permission.value} in order to access"
        )
