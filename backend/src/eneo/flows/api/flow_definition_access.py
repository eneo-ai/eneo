from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, NoReturn
from uuid import UUID

from fastapi import Request

from eneo.actors.actors.space_actor import SpaceActor, SpaceRole
from eneo.authentication.access_denial_code import AccessDenialCode
from eneo.authentication.auth_dependencies import ScopeFilter
from eneo.flows.api import flow_access_context
from eneo.flows.api.flow_runtime_paths import (
    build_published_flow_runtime_endpoint_template,
)
from eneo.flows.flow_access_policy import (
    PUBLISHED_FLOW_RUNTIME_ALTERNATIVE,
    FlowApiAction,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowUnauthorizedException
from eneo.flows.principal import FlowPrincipal
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from eneo.main.exceptions import NotFoundException
from eneo.roles.permissions import Permission

if TYPE_CHECKING:
    from eneo.flows.domain.flow import Flow, FlowSparse


SERVICE_KEY_ADMIN_REQUIRED_MESSAGE = (
    "Service-key principals require admin role to read draft definitions. "
    "Use /api/v1/flows/{id}/published/ for runtime-safe published projections."
)
_SERVICE_KEY_CURRENT_DEFINITION_ROLES = frozenset({SpaceRole.ADMIN, SpaceRole.OWNER})
_FLOW_READ_PERMISSION_MESSAGE = "You do not have permission to access this flow."


@dataclass(frozen=True)
class PublishedFlowRuntimeAccess:
    flow: Flow
    published_version: int


def _raise_service_key_admin_required() -> NoReturn:
    raise FlowUnauthorizedException(
        SERVICE_KEY_ADMIN_REQUIRED_MESSAGE,
        code=FlowApiErrorCode.SERVICE_KEY_ADMIN_REQUIRED,
        context={
            "auth_layer": "service_key_principal",
            "capability": "view_current_definition",
            "required_role": SpaceRole.ADMIN.value,
            "runtime_endpoint_hint": {
                **PUBLISHED_FLOW_RUNTIME_ALTERNATIVE.as_error_context(),
                "endpoint_template": build_published_flow_runtime_endpoint_template(
                    api_prefix=get_settings().api_prefix,
                ),
            },
        },
    )


def _ensure_service_key_can_read_current_definition(
    *,
    principal: FlowPrincipal,
    actor: SpaceActor,
) -> None:
    if not principal.is_service_key:
        return
    if actor.get_current_role() in _SERVICE_KEY_CURRENT_DEFINITION_ROLES:
        return
    _raise_service_key_admin_required()


def _require_flow_reader_actor(
    access_context: flow_access_context.FlowAccessContext,
) -> SpaceActor:
    actor = access_context.actor
    if actor is None or not actor.can_read_flow(access_context.flow):
        raise FlowUnauthorizedException(
            _FLOW_READ_PERMISSION_MESSAGE,
            code=AccessDenialCode.INSUFFICIENT_SPACE_PERMISSION,
            context={"auth_layer": "space_membership"},
        )
    return actor


def _can_override_flow_owner(container: Container, actor: SpaceActor | None) -> bool:
    # Current draft-governance policy is intentionally narrow:
    # - the draft owner always keeps edit authority
    # - tenant admins may override draft ownership tenant-wide
    # - space owners may override draft ownership inside their shared space
    # - space admins/editors still need the owner's cooperation for another member's draft
    user = container.user()
    if Permission.ADMIN in user.permissions:
        return True
    if actor is None:
        return False
    return actor.get_current_role() == SpaceRole.OWNER


class FlowOwnerRequiredException(FlowUnauthorizedException):
    def __init__(self) -> None:
        super().__init__(
            "You do not have permission to modify another member's draft flow.",
            code=FlowApiErrorCode.OWNER_REQUIRED,
            context={"auth_layer": "flow_owner"},
        )


def ensure_can_mutate_flow_draft(
    container: Container,
    *,
    flow: FlowSparse,
    actor: SpaceActor | None,
) -> None:
    """Enforce the current human draft-ownership override rules for flow authoring."""
    user = container.user()
    owner_user_id = flow.owner_user_id or flow.created_by_user_id
    if owner_user_id == user.id:
        return
    if _can_override_flow_owner(container, actor):
        return
    raise FlowOwnerRequiredException()


async def require_flow_current_definition_access(
    request: Request,
    container: Container,
    *,
    flow_id: UUID,
) -> flow_access_context.FlowAccessContext:
    access_context = await flow_access_context.resolve_flow_access_context(
        request,
        container,
        flow_id=flow_id,
        required_access=FlowApiAction.VIEW,
        allow_service_key_principals=True,
    )
    actor = access_context.actor
    if actor is None:
        raise FlowUnauthorizedException(
            _FLOW_READ_PERMISSION_MESSAGE,
            code=AccessDenialCode.INSUFFICIENT_SPACE_PERMISSION,
            context={"auth_layer": "space_membership"},
        )
    _ensure_service_key_can_read_current_definition(
        principal=FlowPrincipal.from_user(container.user()),
        actor=actor,
    )
    _require_flow_reader_actor(access_context)
    return access_context


async def require_flow_published_runtime_access(
    request: Request,
    container: Container,
    *,
    flow_id: UUID,
) -> PublishedFlowRuntimeAccess:
    access_context = await flow_access_context.resolve_flow_access_context(
        request,
        container,
        flow_id=flow_id,
        required_access=FlowApiAction.VIEW,
        allow_service_key_principals=True,
        require_published_for_service_key=True,
    )
    published_version = access_context.flow.published_version
    if published_version is None:
        raise NotFoundException("Flow not found.")

    _require_flow_reader_actor(access_context)
    return PublishedFlowRuntimeAccess(
        flow=access_context.flow,
        published_version=published_version,
    )


async def _require_flow_draft_mutation_access(
    request: Request,
    container: Container,
    *,
    flow_id: UUID,
    can_mutate: Callable[[SpaceActor], bool],
    permission_message: str,
    allow_service_key_principals: bool = False,
) -> flow_access_context.FlowAccessContext:
    access_context = await flow_access_context.resolve_flow_access_context(
        request,
        container,
        flow_id=flow_id,
        required_access=FlowApiAction.EDIT,
        allow_service_key_principals=allow_service_key_principals,
    )
    _ensure_can_mutate(
        container,
        flow=access_context.flow,
        actor=access_context.actor,
        can_mutate=can_mutate,
        permission_message=permission_message,
    )
    return access_context


def _ensure_can_mutate(
    container: Container,
    *,
    flow: FlowSparse,
    actor: SpaceActor | None,
    can_mutate: Callable[[SpaceActor], bool],
    permission_message: str,
) -> None:
    if actor is None or not can_mutate(actor):
        raise FlowUnauthorizedException(
            permission_message,
            code=AccessDenialCode.INSUFFICIENT_SPACE_PERMISSION,
            context={"auth_layer": "space_membership"},
        )
    ensure_can_mutate_flow_draft(container, flow=flow, actor=actor)


def _can_edit(actor: SpaceActor) -> bool:
    return actor.can_edit_flows()


def _can_delete(actor: SpaceActor) -> bool:
    return actor.can_delete_flows()


def _can_publish(actor: SpaceActor) -> bool:
    return actor.can_publish_flows()


_EDIT_PERMISSION_MESSAGE = "You do not have permission to edit flows in this space."
_DELETE_PERMISSION_MESSAGE = "You do not have permission to delete flows in this space."
_PUBLISH_PERMISSION_MESSAGE = (
    "You do not have permission to publish flows in this space."
)


@dataclass(frozen=True, slots=True)
class FlowPermissions:
    """What a caller may do with a flow: whether each action's access checks
    let them through. The flow's state (published or not) is the action's
    own concern."""

    can_edit: bool
    can_publish: bool
    can_delete: bool
    can_run: bool
    can_view_runs: bool


def flow_permissions(
    container: Container,
    *,
    flow: FlowSparse,
    actor: SpaceActor | None,
    scope_filter: ScopeFilter,
) -> FlowPermissions:
    """The caller's permissions on ``flow`` in its space, as ``actor`` holds
    them, by the checks the endpoints make: editing, publishing and deleting
    as ``require_flow_edit_access``, ``require_flow_publish_access`` and
    ``require_flow_delete_access``; running as run creation, and reading runs
    as the run list, through ``enforce_flow_scope``."""

    def allowed(check: Callable[[], None]) -> bool:
        try:
            check()
        except (FlowUnauthorizedException, NotFoundException):
            return False
        return True

    def mutation(can_mutate: Callable[[SpaceActor], bool], message: str) -> bool:
        def check() -> None:
            flow_access_context.check_flow_access(
                container,
                flow,
                scope_filter=scope_filter,
                required_access=FlowApiAction.EDIT,
            )
            _ensure_can_mutate(
                container,
                flow=flow,
                actor=actor,
                can_mutate=can_mutate,
                permission_message=message,
            )

        return allowed(check)

    def scoped(action: FlowApiAction, *, published_for_service_key: bool) -> bool:
        reader = actor
        if reader is None:
            return False
        return allowed(
            lambda: flow_access_context.check_flow_scope(
                container,
                flow,
                actor=reader,
                scope_filter=scope_filter,
                required_access=action,
                allow_service_key_principals=True,
                require_published_for_service_key=published_for_service_key,
            )
        )

    return FlowPermissions(
        can_edit=mutation(_can_edit, _EDIT_PERMISSION_MESSAGE),
        can_publish=mutation(_can_publish, _PUBLISH_PERMISSION_MESSAGE),
        can_delete=mutation(_can_delete, _DELETE_PERMISSION_MESSAGE),
        can_run=scoped(FlowApiAction.RUN, published_for_service_key=True),
        can_view_runs=scoped(FlowApiAction.VIEW, published_for_service_key=False),
    )


async def require_flow_edit_access(
    request: Request,
    container: Container,
    *,
    flow_id: UUID,
    allow_service_key_principals: bool = False,
) -> flow_access_context.FlowAccessContext:
    return await _require_flow_draft_mutation_access(
        request,
        container,
        flow_id=flow_id,
        can_mutate=_can_edit,
        permission_message=_EDIT_PERMISSION_MESSAGE,
        allow_service_key_principals=allow_service_key_principals,
    )


async def require_flow_delete_access(
    request: Request,
    container: Container,
    *,
    flow_id: UUID,
) -> flow_access_context.FlowAccessContext:
    return await _require_flow_draft_mutation_access(
        request,
        container,
        flow_id=flow_id,
        can_mutate=_can_delete,
        permission_message=_DELETE_PERMISSION_MESSAGE,
    )


async def require_flow_publish_access(
    request: Request,
    container: Container,
    *,
    flow_id: UUID,
) -> flow_access_context.FlowAccessContext:
    return await _require_flow_draft_mutation_access(
        request,
        container,
        flow_id=flow_id,
        can_mutate=_can_publish,
        permission_message=_PUBLISH_PERMISSION_MESSAGE,
    )


async def require_flow_unpublish_access(
    request: Request,
    container: Container,
    *,
    flow_id: UUID,
) -> flow_access_context.FlowAccessContext:
    return await _require_flow_draft_mutation_access(
        request,
        container,
        flow_id=flow_id,
        can_mutate=_can_publish,
        permission_message="You do not have permission to unpublish flows in this space.",
    )


__all__ = [
    "FlowOwnerRequiredException",
    "FlowPermissions",
    "PublishedFlowRuntimeAccess",
    "SERVICE_KEY_ADMIN_REQUIRED_MESSAGE",
    "ensure_can_mutate_flow_draft",
    "flow_permissions",
    "require_flow_current_definition_access",
    "require_flow_delete_access",
    "require_flow_edit_access",
    "require_flow_published_runtime_access",
    "require_flow_publish_access",
    "require_flow_unpublish_access",
]
