from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from eneo.audit.domain.actor_types import ActorType
from eneo.authentication.auth_models import (
    ApiKeyPermission,
    ServicePrincipalInDB,
    ServicePrincipalState,
)
from eneo.authentication.principal_types import PrincipalType
from eneo.flows.principal import FlowAuditActorFields, FlowPrincipal
from eneo.users.user import UserInDB


class FlowRunActorError(ValueError):
    pass


class FlowRunServicePrincipalInactiveError(FlowRunActorError):
    pass


@dataclass(frozen=True, slots=True)
class FlowRunActor:
    principal: FlowPrincipal
    tenant_id: UUID
    user: UserInDB | None = None
    service_principal: ServicePrincipalInDB | None = None
    runtime_service_permission: ApiKeyPermission | None = None

    def __post_init__(self) -> None:
        if self.principal.principal_type == PrincipalType.USER:
            if self.user is None:
                raise FlowRunActorError("user actor requires a loaded user")
            if self.service_principal is not None:
                raise FlowRunActorError("user actor must not include service principal")
            if self.runtime_service_permission is not None:
                raise FlowRunActorError(
                    "user actor must not include service permission"
                )
            if self.user.tenant_id != self.tenant_id:
                raise FlowRunActorError("user actor tenant does not match run tenant")
            if self.user.id != self.principal.principal_user_id:
                raise FlowRunActorError("user actor id does not match run principal")
            return

        if self.principal.principal_type != PrincipalType.SERVICE_KEY:
            raise FlowRunActorError("unsupported Flow run principal type")
        if self.service_principal is None:
            raise FlowRunActorError(
                "service-principal actor requires service principal"
            )
        if self.user is not None:
            raise FlowRunActorError("service-principal actor must not include user")
        if self.runtime_service_permission is None:
            raise FlowRunActorError(
                "service-principal actor requires runtime permission"
            )
        if self.service_principal.tenant_id != self.tenant_id:
            raise FlowRunActorError(
                "service-principal actor tenant does not match run tenant"
            )
        if self.service_principal.id != self.principal.principal_service_id:
            raise FlowRunActorError(
                "service-principal actor id does not match run principal"
            )
        service_principal_state = ServicePrincipalState(
            str(
                getattr(
                    self.service_principal.state,
                    "value",
                    self.service_principal.state,
                )
            )
        )
        if service_principal_state != ServicePrincipalState.ACTIVE:
            raise FlowRunServicePrincipalInactiveError(
                "service principal is not active for Flow runtime execution"
            )

    @classmethod
    def from_user(cls, *, user: UserInDB) -> "FlowRunActor":
        return cls(
            principal=FlowPrincipal.from_user(user),
            tenant_id=user.tenant_id,
            user=user,
        )

    @classmethod
    def from_user_run(cls, *, run: object, user: UserInDB) -> "FlowRunActor":
        principal = FlowPrincipal.from_run(run)
        return cls(
            principal=principal,
            tenant_id=getattr(run, "tenant_id"),
            user=user,
        )

    @classmethod
    def from_service_principal_run(
        cls,
        *,
        run: object,
        service_principal: ServicePrincipalInDB,
    ) -> "FlowRunActor":
        principal = FlowPrincipal.from_run(run)
        permission = getattr(run, "runtime_service_permission", None)
        runtime_permission = (
            permission
            if isinstance(permission, ApiKeyPermission)
            else ApiKeyPermission(str(permission))
        )
        return cls(
            principal=principal,
            tenant_id=getattr(run, "tenant_id"),
            service_principal=service_principal,
            runtime_service_permission=runtime_permission,
        )

    @property
    def is_service_principal(self) -> bool:
        return self.principal.principal_type == PrincipalType.SERVICE_KEY

    def audit_actor_fields(self) -> FlowAuditActorFields:
        if not self.is_service_principal:
            return self.principal.audit_actor_fields()
        if self.principal.actor_api_key_id is None:
            return {
                "actor_id": None,
                "actor_type": ActorType.SYSTEM,
                "actor_api_key_id": None,
            }
        return self.principal.audit_actor_fields()

    def audit_actor_snapshot(self) -> dict[str, object]:
        if self.user is not None:
            actor_name = (
                self.user.username
                or getattr(self.user, "name", None)
                or (self.user.email or "").split("@")[0]
                or "unknown"
            )
            return {
                "type": "user",
                "id": str(self.user.id),
                "name": actor_name,
                "email": self.user.email,
            }

        if self.service_principal is None:
            raise FlowRunActorError("service-principal actor is missing")
        snapshot: dict[str, object] = {
            "type": "service_principal",
            "id": str(self.service_principal.id),
            "name": self.service_principal.display_name,
            "scope_type": str(
                getattr(
                    self.service_principal.scope_type,
                    "value",
                    self.service_principal.scope_type,
                )
            ),
            "scope_id": (
                str(self.service_principal.scope_id)
                if self.service_principal.scope_id is not None
                else None
            ),
        }
        if self.principal.actor_api_key_id is not None:
            snapshot["actor_api_key_id"] = str(self.principal.actor_api_key_id)
        return snapshot

    def audit_metadata(
        self, *, target: object, extra: dict[str, object]
    ) -> dict[str, object]:
        target_snapshot: dict[str, object] = {
            "id": str(getattr(target, "id")),
            "name": getattr(target, "name", getattr(target, "title", None)),
        }
        target_space_id = getattr(target, "space_id", None)
        if target_space_id is not None:
            target_snapshot["space_id"] = str(target_space_id)
        return {
            "actor": self.audit_actor_snapshot(),
            "target": target_snapshot,
            "extra": extra,
        }
