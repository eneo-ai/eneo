from __future__ import annotations

from uuid import UUID

from fastapi import Request

from intric.actors.actors.space_actor import SpaceRole
from intric.flows.api import flow_router_common as common
from intric.main.container.container import Container
from intric.main.exceptions import UnauthorizedException
from intric.roles.permissions import Permission


def _can_override_flow_owner(
    container: Container,
    access_context: common.FlowAccessContext,
) -> bool:
    # Current draft-governance policy is intentionally narrow:
    # - the draft owner always keeps edit authority
    # - tenant admins may override draft ownership tenant-wide
    # - space owners may override draft ownership inside their shared space
    # - space admins/editors still need the owner's cooperation for another member's draft
    user = container.user()
    if Permission.ADMIN in user.permissions:
        return True
    actor = access_context.actor
    if actor is None:
        return False
    return actor.get_current_role() == SpaceRole.OWNER


def ensure_can_mutate_flow_draft(
    container: Container,
    access_context: common.FlowAccessContext,
) -> None:
    """Enforce the current human draft-ownership override rules for flow authoring."""
    user = container.user()
    flow = access_context.flow
    owner_user_id = flow.owner_user_id or flow.created_by_user_id
    if owner_user_id == user.id:
        return
    if _can_override_flow_owner(container, access_context):
        return
    raise UnauthorizedException(
        "You do not have permission to modify another member's draft flow.",
        code="flow_owner_required",
        context={"auth_layer": "flow_owner"},
    )


async def require_flow_edit_access(
    request: Request,
    container: Container,
    *,
    flow_id: UUID,
    require_flow_lookup_without_scope: bool = False,
    allow_service_key_principals: bool = False,
) -> common.FlowAccessContext:
    access_context = await common.get_flow_access_context_for_request(
        request,
        container,
        flow_id=flow_id,
        required_access=common.FlowApiAction.EDIT,
        allow_service_key_principals=allow_service_key_principals,
    )
    if require_flow_lookup_without_scope:
        pass
    if access_context.actor is None or not access_context.actor.can_edit_flows():
        raise UnauthorizedException(
            "You do not have permission to edit flows in this space.",
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
        )
    ensure_can_mutate_flow_draft(container, access_context)
    return access_context


__all__ = ["ensure_can_mutate_flow_draft", "require_flow_edit_access"]
