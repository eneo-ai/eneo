from __future__ import annotations

from enum import Enum

from intric.main.exceptions import UnauthorizedException
from intric.roles.permissions import Permission, has_permission
from intric.users.user import UserInDB


def user_can_view_flows(user: UserInDB) -> bool:
    return has_permission(user.permissions, Permission.FLOWS_VIEW)


def user_can_run_flows(user: UserInDB) -> bool:
    return has_permission(user.permissions, Permission.FLOWS_RUN)


def user_can_manage_flows(user: UserInDB) -> bool:
    return has_permission(user.permissions, Permission.FLOWS_MANAGE)


def user_can_use_flow_ai_builder(user: UserInDB) -> bool:
    return has_permission(user.permissions, Permission.FLOWS_AI_BUILDER)


def user_can_view_flow_trace(user: UserInDB) -> bool:
    return has_permission(user.permissions, Permission.FLOWS_TRACE)


def _raise_insufficient_tenant_permission(message: str) -> None:
    raise UnauthorizedException(
        message,
        code="insufficient_tenant_permission",
        context={"auth_layer": "tenant_role"},
    )


def _is_service_key_principal(user: UserInDB) -> bool:
    key = getattr(user, "active_api_key", None)
    if key is None:
        return False
    ownership = getattr(key, "ownership", "user")
    if isinstance(ownership, Enum):
        ownership = ownership.value
    return str(ownership) == "service"


def _raise_service_key_not_supported(*, capability: str) -> None:
    raise UnauthorizedException(
        "This Flows endpoint requires a user principal. Service-key principals cannot use this action.",
        code="flow_service_key_principal_not_supported",
        context={
            "auth_layer": "service_key_principal",
            "capability": capability,
        },
    )


def ensure_can_view_flows(user: UserInDB) -> None:
    if _is_service_key_principal(user):
        _raise_service_key_not_supported(capability="view")
    if not user_can_view_flows(user):
        _raise_insufficient_tenant_permission(
            "You do not have permission to view flows."
        )


def ensure_can_run_flows(user: UserInDB) -> None:
    if _is_service_key_principal(user):
        _raise_service_key_not_supported(capability="run")
    if not user_can_run_flows(user):
        _raise_insufficient_tenant_permission(
            "You do not have permission to run flows."
        )


def ensure_can_manage_flows(user: UserInDB) -> None:
    if _is_service_key_principal(user):
        _raise_service_key_not_supported(capability="manage")
    if not user_can_manage_flows(user):
        _raise_insufficient_tenant_permission(
            "You do not have permission to manage flows."
        )


def ensure_can_use_flow_ai_builder(user: UserInDB) -> None:
    if _is_service_key_principal(user):
        _raise_service_key_not_supported(capability="ai_builder")
    ensure_can_manage_flows(user)
    if not user_can_use_flow_ai_builder(user):
        _raise_insufficient_tenant_permission(
            "You do not have permission to use Flow AI Builder."
        )


def ensure_can_view_flow_trace(user: UserInDB) -> None:
    if _is_service_key_principal(user):
        _raise_service_key_not_supported(capability="trace")
    ensure_can_view_flows(user)
    if not user_can_view_flow_trace(user):
        _raise_insufficient_tenant_permission(
            "You do not have permission to view flow trace."
        )
