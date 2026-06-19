from __future__ import annotations

"""Request-scoped Flow access contexts and gates.

Routers call these gates through this module namespace so tests can patch the
request scope seam in one place without replacing each router's local binding.
"""

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, NoReturn
from uuid import UUID

from fastapi import Request

from intric.authentication.auth_dependencies import ScopeFilter, get_scope_filter
from intric.flows.flow_access_policy import (
    FlowApiAction,
    require_flow_action,
)
from intric.flows.principal import FlowPrincipal
from intric.main.container.container import Container
from intric.main.exceptions import NotFoundException, UnauthorizedException
from intric.users.user import UserInDB

if TYPE_CHECKING:
    from intric.actors.actors.space_actor import SpaceActor
    from intric.flows.domain.flow import Flow
    from intric.spaces.space import Space


@dataclass(frozen=True)
class FlowAccessContext:
    flow: Flow
    scope_filter: ScopeFilter
    space: Space | None = None
    actor: SpaceActor | None = None


@dataclass(frozen=True)
class FlowSpaceAccessContext:
    space: Space
    actor: SpaceActor
    scope_filter: ScopeFilter


def _raise_scope_mismatch(
    message: str = "API key space scope does not match requested flow.",
) -> NoReturn:
    raise UnauthorizedException(
        message,
        code="insufficient_scope",
        context={"auth_layer": "api_key_scope"},
    )


def _scope_type_value(scope_type: object | None) -> str | None:
    if scope_type is None:
        return None
    if isinstance(scope_type, Enum):
        return str(scope_type.value)
    return str(scope_type)


def _ensure_flow_scope_type_allowed(
    scope_filter: ScopeFilter,
    *,
    scope_mismatch_message: str,
) -> None:
    scope_type = _scope_type_value(scope_filter.scope_type)
    if scope_type in {None, "tenant", "space"}:
        return
    _raise_scope_mismatch(scope_mismatch_message)


async def enforce_flow_scope(
    request: Request,
    container: Container,
    *,
    flow_id: UUID,
    required_access: FlowApiAction = FlowApiAction.VIEW,
    allow_service_key_principals: bool = False,
    require_published_for_service_key: bool = False,
) -> None:
    scope_filter = get_scope_filter(request)
    _ensure_flow_scope_type_allowed(
        scope_filter,
        scope_mismatch_message="API key scope does not permit flow access.",
    )
    access_context = await resolve_flow_access_context(
        request,
        container,
        flow_id=flow_id,
        required_access=required_access,
        allow_service_key_principals=allow_service_key_principals,
        require_published_for_service_key=require_published_for_service_key,
        scope_filter=scope_filter,
        load_actor_context=(
            allow_service_key_principals
            or not FlowPrincipal.from_user(container.user()).is_service_key
        ),
    )

    if access_context.actor is not None and not access_context.actor.can_read_flows():
        raise UnauthorizedException(
            "You do not have permission to access flows in this space.",
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
        )
    if access_context.actor is not None and not access_context.actor.can_read_flow(
        access_context.flow
    ):
        raise UnauthorizedException(
            "You do not have permission to access this flow.",
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
        )


def _ensure_required_flow_action(
    user: UserInDB,
    *,
    required_access: FlowApiAction,
    allow_service_key_principals: bool = False,
) -> None:
    require_flow_action(
        user,
        required_access,
        allow_service_key_principals=allow_service_key_principals,
    )


async def resolve_flow_access_context(
    request: Request,
    container: Container,
    *,
    flow_id: UUID,
    required_access: FlowApiAction = FlowApiAction.VIEW,
    allow_service_key_principals: bool = False,
    require_published_for_service_key: bool = False,
    scope_filter: ScopeFilter | None = None,
    load_actor_context: bool = True,
    scope_mismatch_message: str = "API key space scope does not match requested flow.",
) -> FlowAccessContext:
    resolved_scope_filter = scope_filter or get_scope_filter(request)
    _ensure_flow_scope_type_allowed(
        resolved_scope_filter,
        scope_mismatch_message=scope_mismatch_message,
    )

    flow_service = container.flow_service()
    flow = await flow_service.get_flow(flow_id)
    if (
        resolved_scope_filter.space_id is not None
        and resolved_scope_filter.space_id != flow.space_id
    ):
        _raise_scope_mismatch(scope_mismatch_message)

    if (
        require_published_for_service_key
        and allow_service_key_principals
        and FlowPrincipal.from_user(container.user()).is_service_key
        and flow.published_version is None
    ):
        raise NotFoundException("Flow not found.")

    _ensure_required_flow_action(
        container.user(),
        required_access=required_access,
        allow_service_key_principals=allow_service_key_principals,
    )

    if not load_actor_context:
        return FlowAccessContext(
            flow=flow,
            scope_filter=resolved_scope_filter,
        )

    space_service = container.space_service()
    actor_manager = container.actor_manager()
    space = await space_service.get_space(flow.space_id)
    actor = actor_manager.get_space_actor_from_space(space)
    return FlowAccessContext(
        flow=flow,
        scope_filter=resolved_scope_filter,
        space=space,
        actor=actor,
    )


async def resolve_space_access_context(
    request: Request,
    container: Container,
    *,
    space_id: UUID,
    required_access: FlowApiAction = FlowApiAction.VIEW,
    allow_service_key_principals: bool = False,
    scope_filter: ScopeFilter | None = None,
    scope_mismatch_message: str = "API key space scope does not match requested flow.",
) -> FlowSpaceAccessContext:
    resolved_scope_filter = scope_filter or get_scope_filter(request)
    _ensure_flow_scope_type_allowed(
        resolved_scope_filter,
        scope_mismatch_message=scope_mismatch_message,
    )

    if (
        resolved_scope_filter.space_id is not None
        and resolved_scope_filter.space_id != space_id
    ):
        _raise_scope_mismatch(scope_mismatch_message)

    _ensure_required_flow_action(
        container.user(),
        required_access=required_access,
        allow_service_key_principals=allow_service_key_principals,
    )
    space_service = container.space_service()
    actor_manager = container.actor_manager()
    space = await space_service.get_space(space_id)
    actor = actor_manager.get_space_actor_from_space(space)
    return FlowSpaceAccessContext(
        space=space,
        actor=actor,
        scope_filter=resolved_scope_filter,
    )


__all__ = [
    "FlowAccessContext",
    "FlowSpaceAccessContext",
    "enforce_flow_scope",
    "resolve_flow_access_context",
    "resolve_space_access_context",
]
