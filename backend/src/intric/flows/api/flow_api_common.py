from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request, status

from intric.authentication.auth_dependencies import ScopeFilter, get_scope_filter
from intric.main.container.container import Container
from intric.main.exceptions import ErrorCodes, UnauthorizedException
from intric.main.models import GeneralError


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


def raise_scope_mismatch() -> None:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "insufficient_scope",
            "message": "API key space scope does not match requested flow.",
            "context": {"auth_layer": "api_key_scope"},
        },
    )


async def enforce_flow_scope(
    request: Request,
    container: Container,
    *,
    flow_id: UUID,
    require_flow_lookup_without_scope: bool = False,
    scope_filter_getter: Callable[[Request], ScopeFilter] | None = None,
) -> Any | None:
    getter = scope_filter_getter or get_scope_filter
    scope_filter = getter(request)

    # Always load the flow — needed for space membership check
    flow = await container.flow_service().get_flow(flow_id)

    # API key scope check
    if scope_filter.space_id is not None and scope_filter.space_id != flow.space_id:
        raise_scope_mismatch()

    # Space membership check for bearer-token users only.
    # Tenant-scoped API keys (scope_type != None, space_id == None) are already
    # authorized by router-level guards and must NOT be forced through membership.
    if scope_filter.space_id is None and scope_filter.scope_type is None:
        space = await container.space_service().get_space(flow.space_id)
        actor = container.actor_manager().get_space_actor_from_space(space)
        if not actor.can_read_flows():
            raise UnauthorizedException(
                "You do not have permission to access flows in this space.",
                code="insufficient_space_permission",
                context={"auth_layer": "space_membership"},
            )

    return flow
