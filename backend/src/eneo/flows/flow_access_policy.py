from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.principal import FlowPrincipal
from eneo.main.exceptions import UnauthorizedException
from eneo.roles.permissions import Permission, has_permission
from eneo.users.user import UserInDB


class FlowApiAction(str, Enum):
    VIEW = "view"
    RUN = "run"
    EDIT = "edit"
    TRACE_VIEW = "trace_view"
    REVIEW = "review"
    RESUME = "resume"
    AUDIT_VIEW = "audit_view"


class FlowAccessFilterMode(str, Enum):
    VISIBLE = "visible"


class ServiceKeyRuntimeAlternativeKey(str, Enum):
    PUBLISHED_FLOW_RUNTIME = "published_flow_runtime"


@dataclass(frozen=True)
class ServiceKeyRuntimeAlternative:
    key: ServiceKeyRuntimeAlternativeKey
    description: str

    def as_error_context(self) -> dict[str, object]:
        return {
            "key": self.key.value,
            "description": self.description,
        }


PUBLISHED_FLOW_RUNTIME_ALTERNATIVE = ServiceKeyRuntimeAlternative(
    key=ServiceKeyRuntimeAlternativeKey.PUBLISHED_FLOW_RUNTIME,
    description="Use the published runtime projection for service-key Flow clients.",
)


@dataclass(frozen=True)
class FlowActionRequirement:
    required_permissions: tuple[Permission, ...]
    denial_message: str
    service_key_capability: str
    service_key_allowed_when_requested: bool = False
    requires_flow_edit: bool = False
    implemented: bool = True
    service_key_runtime_alternative: ServiceKeyRuntimeAlternative | None = None


FLOW_ACTION_REQUIREMENTS: dict[FlowApiAction, FlowActionRequirement] = {
    FlowApiAction.VIEW: FlowActionRequirement(
        required_permissions=(Permission.FLOWS_VIEW,),
        denial_message="You do not have permission to view flows.",
        service_key_capability="view",
        service_key_allowed_when_requested=True,
        service_key_runtime_alternative=PUBLISHED_FLOW_RUNTIME_ALTERNATIVE,
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
    FlowApiAction.REVIEW: FlowActionRequirement(
        required_permissions=(Permission.FLOWS_MANAGE,),
        denial_message="You do not have permission to review flows.",
        service_key_capability="review",
        service_key_allowed_when_requested=True,
    ),
    FlowApiAction.RESUME: FlowActionRequirement(
        required_permissions=(Permission.FLOWS_MANAGE,),
        denial_message="You do not have permission to resume flows.",
        service_key_capability="resume",
        service_key_allowed_when_requested=True,
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
        raise_service_key_not_supported(
            capability=requirement.service_key_capability,
            runtime_alternative=requirement.service_key_runtime_alternative,
        )
    if not user_can_perform_flow_action(user, action):
        raise_insufficient_tenant_permission(requirement.denial_message)


def raise_insufficient_tenant_permission(message: str) -> None:
    raise UnauthorizedException(
        message,
        code="insufficient_tenant_permission",
        context={"auth_layer": "tenant_role"},
    )


def raise_service_key_not_supported(
    *,
    capability: str,
    runtime_alternative: ServiceKeyRuntimeAlternative | None = None,
) -> None:
    context: dict[str, object] = {
        "auth_layer": "service_key_principal",
        "capability": capability,
    }
    if runtime_alternative is not None:
        context["runtime_endpoint_hint"] = runtime_alternative.as_error_context()

    raise UnauthorizedException(
        "This Flows endpoint requires a user principal. Service-key principals cannot use this action.",
        code=FlowApiErrorCode.SERVICE_KEY_PRINCIPAL_NOT_SUPPORTED.value,
        context=context,
    )
