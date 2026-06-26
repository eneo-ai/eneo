from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict
from uuid import UUID

from intric.audit.domain.actor_types import ActorType
from intric.authentication.principal_types import PrincipalType

if TYPE_CHECKING:
    from intric.users.user import UserInDB


class FlowAuditActorFields(TypedDict):
    actor_id: UUID | None
    actor_type: ActorType
    actor_api_key_id: UUID | None


@dataclass(frozen=True)
class FlowPrincipal:
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
            raise ValueError("flow principals must not set both principal ids")
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
    def from_user(cls, user: UserInDB) -> "FlowPrincipal":
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
    def from_run(cls, run: object) -> "FlowPrincipal":
        principal_type = getattr(run, "principal_type", None)
        principal_user_id = getattr(run, "principal_user_id", None)
        principal_service_id = getattr(run, "principal_service_id", None)
        actor_api_key_id = getattr(run, "created_by_api_key_id", None)
        if principal_type is None:
            raise ValueError("principal_type required for Flow run principals")

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

    def run_create_fields(self) -> dict[str, object | None]:
        return {
            "principal_type": self.principal_type.value,
            "principal_user_id": self.principal_user_id,
            "principal_service_id": self.principal_service_id,
            "created_by_api_key_id": self.actor_api_key_id,
        }

    def file_owner_fields(self) -> dict[str, object | None]:
        return {
            "owner_type": self.principal_type.value,
            "owner_user_id": self.principal_user_id,
            "owner_service_id": self.principal_service_id,
        }

    def audit_actor_fields(self) -> FlowAuditActorFields:
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

    def matches_run(self, run: object) -> bool:
        run_principal = FlowPrincipal.from_run(run)
        return (
            self.principal_type == run_principal.principal_type
            and self.principal_user_id == run_principal.principal_user_id
            and self.principal_service_id == run_principal.principal_service_id
        )
