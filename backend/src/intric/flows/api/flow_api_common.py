from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, TypedDict
from uuid import UUID

from fastapi import HTTPException, Request, status

from intric.audit.domain.actor_types import ActorType
from intric.authentication.auth_dependencies import ScopeFilter, get_scope_filter
from intric.flows.flow_permissions import (
    ensure_can_manage_flows,
    ensure_can_run_flows,
    ensure_can_view_flows,
)
from intric.main.container.container import Container
from intric.main.exceptions import ErrorCodes, NotFoundException, UnauthorizedException
from intric.main.models import GeneralError

if TYPE_CHECKING:
    from intric.actors.actors.space_actor import SpaceActor
    from intric.flows.domain.flow import Flow
    from intric.spaces.space import Space


@dataclass(frozen=True)
class FlowAccessContext:
    flow: "Flow"
    scope_filter: ScopeFilter
    space: "Space | None" = None
    actor: "SpaceActor | None" = None


@dataclass(frozen=True)
class FlowSpaceAccessContext:
    space: "Space"
    actor: "SpaceActor"
    scope_filter: ScopeFilter


class AuditActorKwargs(TypedDict):
    actor_id: UUID | None
    actor_type: ActorType
    actor_api_key_id: UUID | None


def error_response(
    *,
    description: str,
    message: str,
    intric_error_code: ErrorCodes,
    code: str | None = None,
    context: dict[str, object] | None = None,
) -> dict[str, Any]:
    example: dict[str, Any] = {
        "message": message,
        "intric_error_code": int(intric_error_code),
    }
    if code is not None:
        example["code"] = code
    if context is not None:
        example["context"] = context
    return {
        "model": GeneralError,
        "description": description,
        "content": {"application/json": {"example": example}},
    }


def raise_scope_mismatch(
    message: str = "API key space scope does not match requested flow.",
) -> None:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "insufficient_scope",
            "message": message,
            "context": {"auth_layer": "api_key_scope"},
        },
    )


def _scope_type_value(scope_type: object | None) -> str | None:
    if scope_type is None:
        return None
    if isinstance(scope_type, Enum):
        return str(scope_type.value)
    return str(scope_type)


def is_service_key_principal(user: Any) -> bool:
    key = getattr(user, "active_api_key", None)
    if key is None:
        return False
    ownership = getattr(key, "ownership", "user")
    if isinstance(ownership, Enum):
        ownership = ownership.value
    return str(ownership) == "service"


def audit_actor_kwargs(user: Any) -> AuditActorKwargs:
    if is_service_key_principal(user):
        key = getattr(user, "active_api_key", None)
        return {
            "actor_id": None,
            "actor_type": ActorType.API_KEY,
            "actor_api_key_id": getattr(key, "id", None),
        }
    return {
        "actor_id": getattr(user, "id", None),
        "actor_type": ActorType.USER,
        "actor_api_key_id": None,
    }


def _ensure_flow_scope_type_allowed(
    scope_filter: ScopeFilter,
    *,
    scope_mismatch_message: str,
) -> None:
    scope_type = _scope_type_value(scope_filter.scope_type)
    if scope_type in {None, "tenant", "space"}:
        return
    raise_scope_mismatch(scope_mismatch_message)


async def enforce_flow_scope(
    request: Request,
    container: Container,
    *,
    flow_id: UUID,
    required_access: str = "view",
    require_flow_lookup_without_scope: bool = False,
    allow_service_key_principals: bool = False,
    require_published_for_service_key: bool = False,
    scope_filter_getter: Callable[[Request], ScopeFilter] | None = None,
) -> Any | None:
    getter = scope_filter_getter or get_scope_filter
    scope_filter = getter(request)
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
        scope_filter_getter=getter,
        load_actor_context=(
            allow_service_key_principals
            or not is_service_key_principal(container.user())
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

    return access_context.flow


def _ensure_required_tenant_permission(
    user: Any,
    *,
    required_access: str,
    allow_service_key_principals: bool = False,
) -> None:
    if allow_service_key_principals and is_service_key_principal(user):
        if required_access in {"view", "run"}:
            return
    if required_access == "manage":
        ensure_can_manage_flows(user)
    elif required_access == "run":
        ensure_can_run_flows(user)
    else:
        ensure_can_view_flows(user)


async def resolve_flow_access_context(
    request: Request,
    container: Container,
    *,
    flow_id: UUID,
    required_access: str = "view",
    allow_service_key_principals: bool = False,
    require_published_for_service_key: bool = False,
    scope_filter: ScopeFilter | None = None,
    scope_filter_getter: Callable[[Request], ScopeFilter] | None = None,
    load_actor_context: bool = True,
    scope_mismatch_message: str = "API key space scope does not match requested flow.",
) -> FlowAccessContext:
    getter = scope_filter_getter or get_scope_filter
    resolved_scope_filter = scope_filter or getter(request)
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
        raise_scope_mismatch(scope_mismatch_message)

    if (
        require_published_for_service_key
        and allow_service_key_principals
        and is_service_key_principal(container.user())
        and flow.published_version is None
    ):
        raise NotFoundException("Flow not found.")

    _ensure_required_tenant_permission(
        container.user(),
        required_access=required_access,
        allow_service_key_principals=allow_service_key_principals,
    )

    if not load_actor_context:
        return FlowAccessContext(
            flow=flow,
            scope_filter=resolved_scope_filter,
        )

    space_service = container.space_service()  # pyright: ignore[reportUnknownMemberType]
    actor_manager = container.actor_manager()  # pyright: ignore[reportUnknownMemberType]
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
    required_access: str = "view",
    allow_service_key_principals: bool = False,
    scope_filter: ScopeFilter | None = None,
    scope_filter_getter: Callable[[Request], ScopeFilter] | None = None,
    scope_mismatch_message: str = "API key space scope does not match requested flow.",
) -> FlowSpaceAccessContext:
    getter = scope_filter_getter or get_scope_filter
    resolved_scope_filter = scope_filter or getter(request)
    _ensure_flow_scope_type_allowed(
        resolved_scope_filter,
        scope_mismatch_message=scope_mismatch_message,
    )

    if (
        resolved_scope_filter.space_id is not None
        and resolved_scope_filter.space_id != space_id
    ):
        raise_scope_mismatch(scope_mismatch_message)

    _ensure_required_tenant_permission(
        container.user(),
        required_access=required_access,
        allow_service_key_principals=allow_service_key_principals,
    )
    space_service = container.space_service()  # pyright: ignore[reportUnknownMemberType]
    actor_manager = container.actor_manager()  # pyright: ignore[reportUnknownMemberType]
    space = await space_service.get_space(space_id)
    actor = actor_manager.get_space_actor_from_space(space)
    return FlowSpaceAccessContext(
        space=space,
        actor=actor,
        scope_filter=resolved_scope_filter,
    )
