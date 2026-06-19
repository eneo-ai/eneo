from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, NoReturn
from uuid import UUID

from fastapi import Request

from intric.actors.actors.space_actor import SpaceActor, SpaceRole
from intric.flows.api import flow_access_context
from intric.flows.api.flow_runtime_paths import (
    build_published_flow_runtime_endpoint_template,
)
from intric.flows.flow_access_policy import (
    PUBLISHED_FLOW_RUNTIME_ALTERNATIVE,
    FlowApiAction,
)
from intric.flows.flow_api_error_code import FlowApiErrorCode
from intric.flows.principal import FlowPrincipal
from intric.main.config import get_settings
from intric.main.container.container import Container
from intric.main.exceptions import NotFoundException, UnauthorizedException
from intric.roles.permissions import Permission

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow


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
    raise UnauthorizedException(
        SERVICE_KEY_ADMIN_REQUIRED_MESSAGE,
        code=FlowApiErrorCode.SERVICE_KEY_ADMIN_REQUIRED.value,
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
        raise UnauthorizedException(
            _FLOW_READ_PERMISSION_MESSAGE,
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
        )
    return actor


def _can_override_flow_owner(
    container: Container,
    access_context: flow_access_context.FlowAccessContext,
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
    access_context: flow_access_context.FlowAccessContext,
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
        code=FlowApiErrorCode.OWNER_REQUIRED.value,
        context={"auth_layer": "flow_owner"},
    )


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
        raise UnauthorizedException(
            _FLOW_READ_PERMISSION_MESSAGE,
            code="insufficient_space_permission",
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
    actor = access_context.actor
    if actor is None or not can_mutate(actor):
        raise UnauthorizedException(
            permission_message,
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
        )
    ensure_can_mutate_flow_draft(container, access_context)
    return access_context


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
        can_mutate=lambda actor: actor.can_edit_flows(),
        permission_message="You do not have permission to edit flows in this space.",
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
        can_mutate=lambda actor: actor.can_delete_flows(),
        permission_message="You do not have permission to delete flows in this space.",
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
        can_mutate=lambda actor: actor.can_publish_flows(),
        permission_message="You do not have permission to publish flows in this space.",
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
        can_mutate=lambda actor: actor.can_publish_flows(),
        permission_message="You do not have permission to unpublish flows in this space.",
    )


__all__ = [
    "PublishedFlowRuntimeAccess",
    "SERVICE_KEY_ADMIN_REQUIRED_MESSAGE",
    "ensure_can_mutate_flow_draft",
    "require_flow_current_definition_access",
    "require_flow_delete_access",
    "require_flow_edit_access",
    "require_flow_published_runtime_access",
    "require_flow_publish_access",
    "require_flow_unpublish_access",
]
