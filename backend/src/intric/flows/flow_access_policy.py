from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Callable, NoReturn
from uuid import UUID

from intric.flows.principal import FlowPrincipal
from intric.main.exceptions import UnauthorizedException
from intric.roles.permissions import Permission, has_permission
from intric.users.user import UserInDB

if TYPE_CHECKING:
    from intric.authentication.auth_dependencies import ScopeFilter


class FlowApiAction(str, Enum):
    VIEW = "view"
    RUN = "run"
    EDIT = "edit"
    TRACE_VIEW = "trace_view"
    BUILDER_SESSION_CREATE = "builder_session_create"
    BUILDER_SESSION_LIST = "builder_session_list"
    BUILDER_MESSAGE_SEND = "builder_message_send"
    BUILDER_SESSION_READ = "builder_session_read"
    BUILDER_ATTACHMENT_DETACH = "builder_attachment_detach"
    BUILDER_MODELS_LIST = "builder_models_list"
    BUILDER_PLAN_READ = "builder_plan_read"
    BUILDER_PLAN_LIST = "builder_plan_list"
    BUILDER_SESSION_CANCEL = "builder_session_cancel"
    BUILDER_PLAN_APPROVE = "builder_plan_approve"
    BUILDER_PLAN_APPLY = "builder_plan_apply"
    BUILDER_PLAN_REVISE = "builder_plan_revise"
    REVIEW = "review"
    RESUME = "resume"
    RERUN = "rerun"
    AUDIT_VIEW = "audit_view"


class FlowAccessFilterMode(str, Enum):
    VISIBLE = "visible"


@dataclass(frozen=True)
class FlowActionRequirement:
    required_permissions: tuple[Permission, ...]
    denial_message: str
    service_key_capability: str
    service_key_allowed_when_requested: bool = False
    requires_flow_edit: bool = False
    implemented: bool = True


_BUILDER_PERMISSIONS = (
    Permission.FLOWS_MANAGE,
    Permission.FLOWS_AI_BUILDER,
)

FLOW_ACTION_REQUIREMENTS: dict[FlowApiAction, FlowActionRequirement] = {
    FlowApiAction.VIEW: FlowActionRequirement(
        required_permissions=(Permission.FLOWS_VIEW,),
        denial_message="You do not have permission to view flows.",
        service_key_capability="view",
        service_key_allowed_when_requested=True,
    ),
    FlowApiAction.RUN: FlowActionRequirement(
        required_permissions=(Permission.FLOWS_RUN,),
        denial_message="You do not have permission to run flows.",
        service_key_capability="run",
        service_key_allowed_when_requested=True,
    ),
    FlowApiAction.EDIT: FlowActionRequirement(
        required_permissions=(Permission.FLOWS_MANAGE,),
        denial_message="You do not have permission to manage flows.",
        service_key_capability="manage",
        requires_flow_edit=True,
    ),
    FlowApiAction.TRACE_VIEW: FlowActionRequirement(
        required_permissions=(Permission.FLOWS_VIEW, Permission.FLOWS_TRACE),
        denial_message="You do not have permission to view flow trace.",
        service_key_capability="trace",
    ),
    FlowApiAction.BUILDER_SESSION_CREATE: FlowActionRequirement(
        required_permissions=_BUILDER_PERMISSIONS,
        denial_message="You do not have permission to use Flow AI Builder.",
        service_key_capability="ai_builder",
        requires_flow_edit=True,
    ),
    FlowApiAction.BUILDER_SESSION_LIST: FlowActionRequirement(
        required_permissions=_BUILDER_PERMISSIONS,
        denial_message="You do not have permission to use Flow AI Builder.",
        service_key_capability="ai_builder",
        requires_flow_edit=True,
    ),
    FlowApiAction.BUILDER_MESSAGE_SEND: FlowActionRequirement(
        required_permissions=_BUILDER_PERMISSIONS,
        denial_message="You do not have permission to use Flow AI Builder.",
        service_key_capability="ai_builder",
        requires_flow_edit=True,
    ),
    FlowApiAction.BUILDER_SESSION_READ: FlowActionRequirement(
        required_permissions=_BUILDER_PERMISSIONS,
        denial_message="You do not have permission to use Flow AI Builder.",
        service_key_capability="ai_builder",
        requires_flow_edit=True,
    ),
    FlowApiAction.BUILDER_ATTACHMENT_DETACH: FlowActionRequirement(
        required_permissions=_BUILDER_PERMISSIONS,
        denial_message="You do not have permission to use Flow AI Builder.",
        service_key_capability="ai_builder",
        requires_flow_edit=True,
    ),
    FlowApiAction.BUILDER_MODELS_LIST: FlowActionRequirement(
        required_permissions=_BUILDER_PERMISSIONS,
        denial_message="You do not have permission to use Flow AI Builder.",
        service_key_capability="ai_builder",
        requires_flow_edit=True,
    ),
    FlowApiAction.BUILDER_PLAN_READ: FlowActionRequirement(
        required_permissions=_BUILDER_PERMISSIONS,
        denial_message="You do not have permission to use Flow AI Builder.",
        service_key_capability="ai_builder",
        requires_flow_edit=True,
    ),
    FlowApiAction.BUILDER_PLAN_LIST: FlowActionRequirement(
        required_permissions=_BUILDER_PERMISSIONS,
        denial_message="You do not have permission to use Flow AI Builder.",
        service_key_capability="ai_builder",
        requires_flow_edit=True,
    ),
    FlowApiAction.BUILDER_SESSION_CANCEL: FlowActionRequirement(
        required_permissions=_BUILDER_PERMISSIONS,
        denial_message="You do not have permission to use Flow AI Builder.",
        service_key_capability="ai_builder",
        requires_flow_edit=True,
    ),
    FlowApiAction.BUILDER_PLAN_APPROVE: FlowActionRequirement(
        required_permissions=_BUILDER_PERMISSIONS,
        denial_message="You do not have permission to use Flow AI Builder.",
        service_key_capability="ai_builder",
        requires_flow_edit=True,
    ),
    FlowApiAction.BUILDER_PLAN_APPLY: FlowActionRequirement(
        required_permissions=_BUILDER_PERMISSIONS,
        denial_message="You do not have permission to use Flow AI Builder.",
        service_key_capability="ai_builder",
        requires_flow_edit=True,
    ),
    FlowApiAction.BUILDER_PLAN_REVISE: FlowActionRequirement(
        required_permissions=_BUILDER_PERMISSIONS,
        denial_message="You do not have permission to use Flow AI Builder.",
        service_key_capability="ai_builder",
        requires_flow_edit=True,
    ),
    FlowApiAction.REVIEW: FlowActionRequirement(
        required_permissions=(),
        denial_message="You do not have permission to review flows.",
        service_key_capability="review",
        implemented=False,
    ),
    FlowApiAction.RESUME: FlowActionRequirement(
        required_permissions=(),
        denial_message="You do not have permission to resume flows.",
        service_key_capability="resume",
        implemented=False,
    ),
    FlowApiAction.RERUN: FlowActionRequirement(
        required_permissions=(Permission.FLOWS_MANAGE,),
        denial_message="You do not have permission to rerun flows.",
        service_key_capability="rerun",
    ),
    FlowApiAction.AUDIT_VIEW: FlowActionRequirement(
        required_permissions=(),
        denial_message="You do not have permission to view flow audit records.",
        service_key_capability="audit_view",
        implemented=False,
    ),
}


def action_requirement(action: FlowApiAction) -> FlowActionRequirement:
    return FLOW_ACTION_REQUIREMENTS[action]


def user_can_perform_flow_action(user: UserInDB, action: FlowApiAction) -> bool:
    requirement = action_requirement(action)
    if not requirement.implemented:
        return False
    return all(
        has_permission(user.permissions, permission)
        for permission in requirement.required_permissions
    )


def require_flow_action(
    user: UserInDB,
    action: FlowApiAction,
    *,
    allow_service_key_principals: bool = False,
) -> None:
    requirement = action_requirement(action)
    principal = FlowPrincipal.from_user(user)
    if principal.is_service_key:
        if (
            allow_service_key_principals
            and requirement.service_key_allowed_when_requested
        ):
            return
        raise_service_key_not_supported(capability=requirement.service_key_capability)
    if not user_can_perform_flow_action(user, action):
        raise_insufficient_tenant_permission(requirement.denial_message)


def raise_insufficient_tenant_permission(message: str) -> None:
    raise UnauthorizedException(
        message,
        code="insufficient_tenant_permission",
        context={"auth_layer": "tenant_role"},
    )


def raise_service_key_not_supported(*, capability: str) -> None:
    raise UnauthorizedException(
        "This Flows endpoint requires a user principal. Service-key principals cannot use this action.",
        code="flow_service_key_principal_not_supported",
        context={
            "auth_layer": "service_key_principal",
            "capability": capability,
        },
    )


def require_ai_builder_space_scope(
    scope_filter: ScopeFilter,
    *,
    space_id: UUID,
    raise_scope_mismatch: Callable[[], NoReturn],
) -> None:
    scoped_space_id = ai_builder_scoped_space_id(scope_filter)
    if scoped_space_id is not None and scoped_space_id != space_id:
        raise_scope_mismatch()


def ai_builder_scoped_space_id(scope_filter: ScopeFilter) -> UUID | None:
    if scope_filter.scope_type != "space":
        return None
    return scope_filter.space_id
