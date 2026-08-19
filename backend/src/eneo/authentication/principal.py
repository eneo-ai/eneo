from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict
from uuid import UUID

from eneo.audit.domain.actor_types import ActorType
from eneo.authentication.principal_types import PrincipalType
from eneo.files.file_models import FileOwner

if TYPE_CHECKING:
    from eneo.users.user import UserInDB


class PrincipalAuditActorFields(TypedDict):
    actor_id: UUID | None
    actor_type: ActorType
    actor_api_key_id: UUID | None


@dataclass(frozen=True)
class Principal:
    """Stable user or service identity used by tenant-owned resources."""

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
    def from_user(cls, user: UserInDB) -> Principal:
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

    @classmethod
    def from_owner_snapshot(cls, resource: object) -> Principal:
        principal_type = getattr(resource, "principal_type", None)
        principal_user_id = getattr(resource, "principal_user_id", None)
        principal_service_id = getattr(resource, "principal_service_id", None)
        actor_api_key_id = getattr(resource, "created_by_api_key_id", None)
        if principal_type is None:
            raise ValueError("principal_type required for resource principals")

        resolved_type = (
            principal_type
            if isinstance(principal_type, PrincipalType)
            else PrincipalType(str(principal_type))
        )
        return cls(
            principal_type=resolved_type,
            principal_user_id=principal_user_id,
            principal_service_id=principal_service_id,
            actor_api_key_id=actor_api_key_id,
        )

    @classmethod
    def from_run(cls, run: object) -> Principal:
        """Compatibility name for Flow run ownership snapshots."""

        return cls.from_owner_snapshot(run)

    def file_owner_fields(self) -> dict[str, object | None]:
        return {
            "owner_type": self.principal_type.value,
            "owner_user_id": self.principal_user_id,
            "owner_service_id": self.principal_service_id,
        }

    def file_owner(self, *, tenant_id: UUID) -> FileOwner:
        return FileOwner(
            tenant_id=tenant_id,
            owner_type=self.principal_type,
            owner_user_id=self.principal_user_id,
            owner_service_id=self.principal_service_id,
        )

    def audit_actor_fields(self) -> PrincipalAuditActorFields:
        if self.principal_type == PrincipalType.SERVICE_KEY:
            if self.actor_api_key_id is None:
                return {
                    "actor_id": None,
                    "actor_type": ActorType.SYSTEM,
                    "actor_api_key_id": None,
                }
            return {
                "actor_id": None,
                "actor_type": ActorType.API_KEY,
                "actor_api_key_id": self.actor_api_key_id,
            }
        return {
            "actor_id": self.principal_user_id,
            "actor_type": ActorType.USER,
            "actor_api_key_id": None,
        }

    def matches_owner_snapshot(self, resource: object) -> bool:
        owner = Principal.from_owner_snapshot(resource)
        return (
            self.principal_type == owner.principal_type
            and self.principal_user_id == owner.principal_user_id
            and self.principal_service_id == owner.principal_service_id
        )

    def owns_file(self, owner: FileOwner, *, tenant_id: UUID) -> bool:
        """Require both tenant and stable principal identity to match a file."""

        return (
            owner.tenant_id == tenant_id
            and owner.owner_type == self.principal_type
            and owner.owner_user_id == self.principal_user_id
            and owner.owner_service_id == self.principal_service_id
        )

    def matches_run(self, run: object) -> bool:
        """Compatibility name for Flow run ownership checks."""

        return self.matches_owner_snapshot(run)
