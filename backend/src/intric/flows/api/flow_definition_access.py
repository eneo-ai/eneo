from __future__ import annotations

from uuid import UUID

from fastapi import Request

from intric.flows.api import flow_router_common as common
from intric.main.container.container import Container
from intric.main.exceptions import UnauthorizedException


async def require_flow_edit_access(
    request: Request,
    container: Container,
    *,
    flow_id: UUID,
    require_flow_lookup_without_scope: bool = False,
) -> common.FlowAccessContext:
    access_context = await common.get_flow_access_context_for_request(
        request,
        container,
        flow_id=flow_id,
        required_access="manage",
    )
    if require_flow_lookup_without_scope:
        pass
    if access_context.actor is None or not access_context.actor.can_edit_flows():
        raise UnauthorizedException(
            "You do not have permission to edit flows in this space.",
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
        )
    return access_context


__all__ = ["require_flow_edit_access"]
