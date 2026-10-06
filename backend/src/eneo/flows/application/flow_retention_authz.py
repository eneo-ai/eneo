"""Who may change, stop or postpone retention deletion of Flow run history.

The one owner of retention authorization; every retention route and service
path calls it. Only signed-in people decide: a request authenticated with any
API key (user-owned or service) is refused whatever its permissions, because
stopping or changing retention must always name a person.

- retention_manage: rules at Organization/Space/Flow level, the review queue
  and the explicit purge.
- retention_holds: place, extend the review of, and release legal holds.
- Either permission may read the shared status views (Flow targets, holds,
  effective rules).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from eneo.main.exceptions import UnauthorizedException
from eneo.roles.permissions import Permission, has_permission

if TYPE_CHECKING:
    from eneo.users.user import UserInDB

RETENTION_PERMISSION_REQUIRED_CODE: Final = "retention_permission_required"
RETENTION_PERSON_REQUIRED_CODE: Final = "retention_person_required"


def require_retention_manage(user: UserInDB) -> None:
    _require(user, (Permission.RETENTION_MANAGE,))


def require_retention_holds(user: UserInDB) -> None:
    _require(user, (Permission.RETENTION_HOLDS,))


def require_retention_view(user: UserInDB) -> None:
    _require(user, (Permission.RETENTION_MANAGE, Permission.RETENTION_HOLDS))


def _require(user: UserInDB, any_of: tuple[Permission, ...]) -> None:
    if getattr(user, "active_api_key", None) is not None:
        raise UnauthorizedException(
            "Retention can only be changed or stopped by a signed-in person, "
            "not with an API key.",
            code=RETENTION_PERSON_REQUIRED_CODE,
        )
    if not any(has_permission(user.permissions, permission) for permission in any_of):
        raise UnauthorizedException(
            "Need permission "
            + " or ".join(permission.value for permission in any_of)
            + ".",
            code=RETENTION_PERMISSION_REQUIRED_CODE,
        )
