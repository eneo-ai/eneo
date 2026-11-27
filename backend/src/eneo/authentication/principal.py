from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict
from uuid import UUID

from eneo.authentication.principal_types import PrincipalType

if TYPE_CHECKING:
    from eneo.users.user import UserInDB, UserSparse


class CreatorColumns(TypedDict):
    """The two columns that record who made a row: exactly one is set."""

    user_id: UUID | None
    created_by_service_id: UUID | None


@dataclass(frozen=True)
class Principal:
    """Who is acting: a person, the service principal behind a service key,
    or a space running its own scheduled work.

    A service key signs in as a made-up user whose id is the key's id and has
    no row in ``users``, so that id must never be stored as a user. The stable
    identity of a service is its service principal. A space acting for itself
    has no identity to record: what it writes has no creator.
    """

    principal_type: PrincipalType
    principal_user_id: UUID | None = None
    principal_service_id: UUID | None = None
    actor_api_key_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.principal_type == PrincipalType.USER and self.principal_user_id is None:
            raise ValueError("principal_user_id required for user principals")
        if (
            self.principal_type == PrincipalType.SERVICE_KEY
            and self.principal_service_id is None
        ):
            raise ValueError("principal_service_id required for service-key principals")
        if self.principal_user_id is not None and self.principal_service_id is not None:
            raise ValueError("principals must not set both principal ids")
        if (
            self.principal_type == PrincipalType.USER
            and self.actor_api_key_id is not None
        ):
            raise ValueError(
                "actor_api_key_id is only valid for service-key principals"
            )

    @property
    def is_service_key(self) -> bool:
        return self.principal_type == PrincipalType.SERVICE_KEY

    @classmethod
    def from_user(cls, user: UserInDB | UserSparse) -> Principal:
        if isinstance(getattr(user, "acting_space_id", None), UUID):
            return cls(principal_type=PrincipalType.SPACE)
        key = getattr(user, "active_api_key", None)
        if key is not None:
            ownership = getattr(key, "ownership", "user")
            ownership_value = str(getattr(ownership, "value", ownership))
            if ownership_value == "service":
                service_principal_id = getattr(key, "service_principal_id", None)
                if service_principal_id is None:
                    raise ValueError(
                        "service_principal_id required for service-key principals"
                    )
                return cls(
                    principal_type=PrincipalType.SERVICE_KEY,
                    principal_service_id=service_principal_id,
                    actor_api_key_id=key.id,
                )
        return cls(
            principal_type=PrincipalType.USER,
            principal_user_id=user.id,
        )

    def creator_columns(self) -> CreatorColumns:
        """How this principal is recorded as the maker of a row."""
        return {
            "user_id": self.principal_user_id,
            "created_by_service_id": self.principal_service_id,
        }
