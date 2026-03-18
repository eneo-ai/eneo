from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request, status

from intric.authentication.auth_dependencies import ScopeFilter, get_scope_filter
from intric.main.container.container import Container
from intric.main.exceptions import ErrorCodes, UnauthorizedException
from intric.main.models import GeneralError
from intric.flows.flow_permissions import (
    ensure_can_manage_flows,
    ensure_can_run_flows,
    ensure_can_view_flows,
)


@dataclass(frozen=True)
class FlowAccessContext:
    flow: Any
    scope_filter: ScopeFilter
    space: Any | None = None
    actor: Any | None = None


@dataclass(frozen=True)
class FlowSpaceAccessContext:
    space: Any
    actor: Any
    scope_filter: ScopeFilter


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


async def enforce_flow_scope(
    request: Request,
    container: Container,
    *,
    flow_id: UUID,
    required_access: str = "view",
    require_flow_lookup_without_scope: bool = False,
    scope_filter_getter: Callable[[Request], ScopeFilter] | None = None,
) -> Any | None:
    getter = scope_filter_getter or get_scope_filter
    scope_filter = getter(request)
    access_context = await resolve_flow_access_context(
        request,
        container,
        flow_id=flow_id,
        required_access=required_access,
        scope_filter=scope_filter,
        scope_filter_getter=getter,
        load_actor_context=scope_filter.space_id is None and scope_filter.scope_type is None,
    )

    if access_context.actor is not None and not access_context.actor.can_read_flows():
        raise UnauthorizedException(
            "You do not have permission to access flows in this space.",
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
        )

    return access_context.flow


def _ensure_required_tenant_permission(user: Any, *, required_access: str) -> None:
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
    scope_filter: ScopeFilter | None = None,
    scope_filter_getter: Callable[[Request], ScopeFilter] | None = None,
    load_actor_context: bool = True,
    scope_mismatch_message: str = "API key space scope does not match requested flow.",
) -> FlowAccessContext:
    getter = scope_filter_getter or get_scope_filter
    resolved_scope_filter = scope_filter or getter(request)

    flow = await container.flow_service().get_flow(flow_id)
    if (
        resolved_scope_filter.space_id is not None
        and resolved_scope_filter.space_id != flow.space_id
    ):
        raise_scope_mismatch(scope_mismatch_message)

    _ensure_required_tenant_permission(
        container.user(),
        required_access=required_access,
    )

    if not load_actor_context:
        return FlowAccessContext(
            flow=flow,
            scope_filter=resolved_scope_filter,
        )

    space = await container.space_service().get_space(flow.space_id)
    actor = container.actor_manager().get_space_actor_from_space(space)
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
    scope_filter: ScopeFilter | None = None,
    scope_filter_getter: Callable[[Request], ScopeFilter] | None = None,
    scope_mismatch_message: str = "API key space scope does not match requested flow.",
) -> FlowSpaceAccessContext:
    getter = scope_filter_getter or get_scope_filter
    resolved_scope_filter = scope_filter or getter(request)

    if (
        resolved_scope_filter.space_id is not None
        and resolved_scope_filter.space_id != space_id
    ):
        raise_scope_mismatch(scope_mismatch_message)

    _ensure_required_tenant_permission(
        container.user(),
        required_access=required_access,
    )
    space = await container.space_service().get_space(space_id)
    actor = container.actor_manager().get_space_actor_from_space(space)
    return FlowSpaceAccessContext(
        space=space,
        actor=actor,
        scope_filter=resolved_scope_filter,
    )
