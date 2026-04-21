# MIT License

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Coroutine, TypeVar

from intric.main.exceptions import UnauthorizedException

if TYPE_CHECKING:
    from intric.users.user import UserInDB

_F = TypeVar("_F", bound=Callable[..., Coroutine[Any, Any, Any]])


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
    SHARED_SPACES = "shared_spaces"


def validate_permissions(permission: Permission) -> Callable[[_F], _F]:
    """This decorator can only be used on class methods
    where a user exists in the `self`.
    """

    def _validate(func: _F) -> _F:
        async def _inner(self: Any, *args: Any, **kwargs: Any) -> Any:
            if permission not in self.user.permissions:
                raise UnauthorizedException(
                    f"Need permission {permission.value} in order to access"
                )

            return await func(self, *args, **kwargs)

        return _inner  # type: ignore[return-value]  # TypeVar bound wrapping

    return _validate  # type: ignore[return-value]  # TypeVar bound wrapping


def validate_permission(user: UserInDB, permission: Permission):
    if permission not in user.permissions:
        raise UnauthorizedException(
            f"Need permission {permission.value} in order to access"
        )
