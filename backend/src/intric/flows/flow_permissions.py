from __future__ import annotations

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


def _raise_insufficient_tenant_permission(message: str) -> None:
    raise UnauthorizedException(
        message,
        code="insufficient_tenant_permission",
        context={"auth_layer": "tenant_role"},
    )


def ensure_can_view_flows(user: UserInDB) -> None:
    if not user_can_view_flows(user):
        _raise_insufficient_tenant_permission(
            "You do not have permission to view flows."
        )


def ensure_can_run_flows(user: UserInDB) -> None:
    if not user_can_run_flows(user):
        _raise_insufficient_tenant_permission(
            "You do not have permission to run flows."
        )


def ensure_can_manage_flows(user: UserInDB) -> None:
    if not user_can_manage_flows(user):
        _raise_insufficient_tenant_permission(
            "You do not have permission to manage flows."
        )


def ensure_can_use_flow_ai_builder(user: UserInDB) -> None:
    ensure_can_manage_flows(user)
    if not user_can_use_flow_ai_builder(user):
        _raise_insufficient_tenant_permission(
            "You do not have permission to use Flow AI Builder."
        )
