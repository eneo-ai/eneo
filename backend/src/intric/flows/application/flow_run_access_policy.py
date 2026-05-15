from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol, TypeGuard, get_args
from uuid import UUID

from intric.flows.domain.flow import FlowRun
from intric.flows.flow_evidence_policy import (
    EvidenceCapabilityLevel,
    FlowEvidencePolicy,
    classification_level_for_space,
    flow_metadata_marks_sensitive,
    resolve_flow_evidence_policy,
    resolve_service_key_evidence_capability,
)
from intric.flows.flow_permissions import user_can_view_flow_trace
from intric.flows.infrastructure.flow_repo import FlowRepository
from intric.flows.infrastructure.flow_run_repo import FlowRunRepository
from intric.flows.principal import FlowPrincipal
from intric.main.exceptions import UnauthorizedException
from intric.roles.permissions import Permission
from intric.users.user import UserInDB

if TYPE_CHECKING:
    from intric.actors.actors.space_actor import SpaceActor
    from intric.spaces.space import Space


FlowRunAccessKind = Literal[
    "status",
    "cancel",
    "content",
    "rerun",
    "artifact",
    "evidence_view",
    "evidence_export_redacted",
    "evidence_export_raw",
]
_FLOW_RUN_ACCESS_KINDS = set(get_args(FlowRunAccessKind))
FlowRunSpaceRole = Literal["admin", "owner"]


class FlowRunSpaceServiceProtocol(Protocol):
    async def get_space(self, space_id: UUID) -> "Space": ...


class FlowRunActorManagerProtocol(Protocol):
    def get_space_actor_from_space(self, space: "Space") -> "SpaceActor": ...


class FlowRunAccessPolicy:
    def __init__(
        self,
        *,
        user: UserInDB,
        flow_repo: FlowRepository,
        flow_run_repo: FlowRunRepository,
        space_service: FlowRunSpaceServiceProtocol | None = None,
        actor_manager: FlowRunActorManagerProtocol | None = None,
    ):
        self.user = user
        self.flow_repo = flow_repo
        self.flow_run_repo = flow_run_repo
        self.space_service = space_service
        self.actor_manager = actor_manager

    def is_tenant_admin(self) -> bool:
        return Permission.ADMIN in self.user.permissions

    def principal(self) -> FlowPrincipal:
        return FlowPrincipal.from_user(self.user)

    async def load_run(
        self,
        *,
        run_id: UUID,
        flow_id: UUID | None = None,
        access_kind: FlowRunAccessKind = "status",
    ) -> FlowRun:
        run = await self.flow_run_repo.get(
            run_id=run_id,
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
        )
        await self.ensure_can_access_run(run, access_kind=access_kind)
        return run

    async def load_space_access(
        self, *, flow_id: UUID
    ) -> tuple["SpaceActor | None", int]:
        if self.space_service is None or self.actor_manager is None:
            return None, 0
        flow = await self.flow_repo.get(flow_id=flow_id, tenant_id=self.user.tenant_id)
        space = await self.space_service.get_space(flow.space_id)
        actor = self.actor_manager.get_space_actor_from_space(space)
        return actor, classification_level_for_space(space)

    async def space_role(self, *, flow_id: UUID) -> FlowRunSpaceRole | None:
        actor, _classification_level = await self.load_space_access(flow_id=flow_id)
        return self._space_role_from_actor(actor)

    @staticmethod
    def _space_role_from_actor(actor: "SpaceActor | None") -> FlowRunSpaceRole | None:
        if actor is None:
            return None
        current_role = actor.get_current_role()
        role_value = getattr(current_role, "value", current_role)
        if role_value in {"admin", "owner"}:
            return "admin" if role_value == "admin" else "owner"
        return None

    async def can_list_all_runs_in_flow(self, *, flow_id: UUID) -> bool:
        return await self.space_role(flow_id=flow_id) in {"admin", "owner"}

    async def ensure_can_access_run(
        self,
        run: FlowRun,
        *,
        access_kind: FlowRunAccessKind,
    ) -> None:
        if not self._is_known_access_kind(access_kind):
            self.deny_run_access(auth_layer="flow_run_access_kind")
        if run.tenant_id != self.user.tenant_id:
            self.deny_run_access(auth_layer="tenant_isolation")
        if access_kind in {"evidence_export_redacted", "evidence_export_raw"}:
            await self._ensure_sensitive_flow_export_allowed(flow_id=run.flow_id)
        if self.is_tenant_admin():
            return
        principal = self.principal()
        if principal.is_service_key:
            if not principal.matches_run(run):
                self.deny_run_access(auth_layer="flow_run_principal")
            capability = resolve_service_key_evidence_capability(self.user)
            policy = self._evidence_policy()
            _actor, classification_level = await self.load_space_access(
                flow_id=run.flow_id
            )
            if access_kind in {"status", "cancel", "content", "rerun", "artifact"}:
                return
            if access_kind == "evidence_view":
                if capability >= EvidenceCapabilityLevel.VIEW:
                    return
                self.deny_evidence_access(
                    auth_layer="flow_run_principal",
                    message="Service principal is not authorized to view evidence for this run.",
                )
            if access_kind == "evidence_export_redacted":
                if capability >= EvidenceCapabilityLevel.REDACTED_EXPORT:
                    return
                self.deny_evidence_access(
                    auth_layer="flow_run_principal",
                    message="Service principal is not authorized to export evidence for this run.",
                )
            if access_kind == "evidence_export_raw":
                if capability < EvidenceCapabilityLevel.RAW_EXPORT:
                    self.deny_evidence_access(
                        auth_layer="flow_run_principal",
                        message="Service principal is not authorized to export raw evidence for this run.",
                    )
                if (
                    classification_level >= 3
                    and not policy.allow_service_key_raw_export_class3
                ):
                    self.deny_raw_export_access(
                        auth_layer="flow_run_principal",
                        message="Raw evidence export is not allowed for service principals in classification 3 spaces.",
                    )
                return
            self.deny_run_access(auth_layer="flow_run_principal")

        actor, classification_level = await self.load_space_access(flow_id=run.flow_id)
        role_value = self._space_role_from_actor(actor)
        policy = self._evidence_policy()

        if role_value in {"admin", "owner"}:
            if access_kind in {
                "status",
                "cancel",
                "content",
                "rerun",
                "artifact",
                "evidence_view",
                "evidence_export_redacted",
            }:
                return
            if access_kind == "evidence_export_raw":
                if role_value == "owner":
                    return
                if (
                    classification_level < 3
                    or policy.allow_space_admin_raw_export_class3
                ):
                    return
                self.deny_raw_export_access(
                    auth_layer="space_membership",
                    message="Raw evidence export is not allowed for space admins in classification 3 spaces.",
                )

        if principal.matches_run(run):
            if access_kind in {"status", "cancel", "content", "rerun", "artifact"}:
                return
            if access_kind in {"evidence_view", "evidence_export_redacted"}:
                if user_can_view_flow_trace(self.user):
                    return
                raise UnauthorizedException(
                    "You do not have permission to view flow trace.",
                    code="insufficient_tenant_permission",
                    context={"auth_layer": "tenant_role"},
                )
            if access_kind == "evidence_export_raw":
                if not user_can_view_flow_trace(self.user):
                    raise UnauthorizedException(
                        "You do not have permission to view flow trace.",
                        code="insufficient_tenant_permission",
                        context={"auth_layer": "tenant_role"},
                    )
                if classification_level < 3 or policy.allow_run_owner_raw_export_class3:
                    return
                self.deny_raw_export_access(
                    auth_layer="flow_run_owner",
                    message="Raw evidence export is not allowed for this run in a classification 3 space.",
                )

        self.deny_run_access(auth_layer="flow_run_owner")

    async def _ensure_sensitive_flow_export_allowed(self, *, flow_id: UUID) -> None:
        flow = await self.flow_repo.get(flow_id=flow_id, tenant_id=self.user.tenant_id)
        if (
            flow_metadata_marks_sensitive(flow.metadata_json)
            and not self._evidence_policy().allow_sensitive_flow_exports
        ):
            self.deny_evidence_access(
                auth_layer="flow_runtime_policy",
                message="Evidence export is disabled by policy for this sensitive flow.",
            )

    def _evidence_policy(self) -> FlowEvidencePolicy:
        tenant = getattr(self.user, "tenant", None)
        tenant_flow_settings = getattr(tenant, "flow_settings", None)
        return resolve_flow_evidence_policy(tenant_flow_settings)

    @staticmethod
    def _is_known_access_kind(access_kind: object) -> TypeGuard[FlowRunAccessKind]:
        return isinstance(access_kind, str) and access_kind in _FLOW_RUN_ACCESS_KINDS

    @staticmethod
    def deny_run_access(*, auth_layer: str) -> None:
        raise UnauthorizedException(
            "You do not have access to this flow run.",
            code="flow_run_access_denied",
            context={"auth_layer": auth_layer},
        )

    @staticmethod
    def deny_evidence_access(*, auth_layer: str, message: str) -> None:
        raise UnauthorizedException(
            message,
            code="flow_run_evidence_forbidden",
            context={"auth_layer": auth_layer},
        )

    @staticmethod
    def deny_raw_export_access(*, auth_layer: str, message: str) -> None:
        raise UnauthorizedException(
            message,
            code="flow_run_evidence_raw_export_forbidden",
            context={"auth_layer": auth_layer},
        )
